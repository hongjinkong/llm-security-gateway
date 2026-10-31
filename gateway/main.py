"""LLM Security Gateway — 세 API(Chat Completions·Responses·Messages)의 검사 프록시.

요청: 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 어댑터 파싱(400) → 검사기 체인(인젝션 → PII) → 상류.
응답: 대체값 복원(스트리밍은 조각 경계·채널별, gateway/streaming.py) → 감사 한 줄(원문 없음).

D-107 A: 클라이언트 키 인증(GATEWAY_CLIENT_KEYS, 없으면 기동 실패 — GATEWAY_AUTH=off로만 연다)과 상류 키 보관
     (GATEWAY_UPSTREAM_KEY). 볼트는 요청 단위다 — 응답(스트림)이 끝나면 버린다.
D-109: 경로 허용 목록 — 세 POST와 GET /v1/models만 받고 그 밖은 404(상류에 연결하지 않는다). 요청·응답 헤더도 허용 목록.
     /__gateway/health는 status만, 상세(info)와 metrics는 GATEWAY_ADMIN_KEY가 있어야 보인다.
D-118: 앱은 `create_app(settings)`로 만든다(설정은 gateway/settings.py, 상류 중계는 gateway/relay.py, 감사 줄 모양은 gateway/audit.py).
     이 모듈의 `app`은 uvicorn용이다 — 환경변수를 한 번 읽는다. `.env`는 읽지 않는다(`uvicorn --env-file .env`).
D-124: 읽기 전용 운영 대시보드 — /__gateway/dashboard(정적 HTML, CSP 해시)와 /__gateway/stats(관리 키, gateway/metrics.py의 snapshot).
     FastAPI 기본 문서 경로(/docs·/redoc·/openapi.json)와 끝 '/' 리다이렉트(307)는 없다. 파싱 400·허용 목록 밖 404의 감사 `error`도 채운다.
"""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import re
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from functools import partial
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path

import anyio
import httpx
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from gateway.api import ApiError, Doc, adapter_for, error_format_for
from gateway.audit import AuditLog, digest, record
from gateway.auth import Auth
from gateway.detectors.pii import PIIDetector
from gateway.messages import t
from gateway.metrics import Metrics
from gateway.ratelimit import RateLimiter
from gateway.relay import UpstreamClient, UpstreamPool, downstream, read_body, read_capped, relay, send
from gateway.settings import API_NAMES, DETECTOR_REGISTRY, Registry, Settings, build_chain
from gateway.version import VERSION, code_fingerprint

# 게이트웨이 자체 경로. 감사 로그에서 제외한다 — 헬스체크가 초당 여러 번 때리면 지연 통계가 오염된다.
INTERNAL_PREFIX = "/__gateway/"

router = APIRouter()


def _csp(html: bytes) -> str:
    """대시보드의 CSP(D-124) — 유일한 `<script>`·`<style>` 블록의 SHA-256만 허용한다. 블록이 하나가 아니면 여기서 ValueError(기동 실패).
    해시는 줄 끝을 LF로 바꾼 뒤 잰다 — 브라우저가 HTML을 읽을 때 CRLF·CR을 LF로 바꾼 뒤 재기 때문이다. CRLF로 체크아웃한 파일(Windows autocrlf)도 맞는다."""
    (script,) = re.findall(rb"<script>(.*?)</script>", html, re.S)
    (style,) = re.findall(rb"<style>(.*?)</style>", html, re.S)

    def sha(block: bytes) -> str:
        block = block.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return "'sha256-" + base64.b64encode(hashlib.sha256(block).digest()).decode() + "'"
    return (f"default-src 'none'; script-src {sha(script)}; style-src {sha(style)}; img-src data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'")


DASHBOARD = Path(__file__).with_name("dashboard.html").read_bytes()
DASHBOARD_HEADERS = {"Content-Security-Policy": _csp(DASHBOARD), "X-Content-Type-Options": "nosniff",
                     "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


def create_app(settings: Settings, registry: Registry = DETECTOR_REGISTRY) -> FastAPI:
    """설정 하나 → 앱 하나. 무거운 준비(상류 클라이언트·검사기)는 lifespan에서 한다."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings
        if not s.clients and not s.auth_off:
            raise RuntimeError(t("no_client_keys", s.lang))
        upstreams = {api: s.upstream(api) for api in API_NAMES}
        if s.auth_off and any(u.key for u in upstreams.values()):
            raise RuntimeError(t("auth_off_with_key", s.lang))
        app.state.settings = s
        app.state.auth = Auth(None if s.auth_off else dict(s.clients))
        # 상류마다 연결 풀 하나(같은 주소·시간 제한이면 함께 쓴다, D-119). 요청마다 새로 만들면 매번 TCP·TLS 핸드셰이크다.
        # 풀은 연결 하나짜리 클라이언트를 빌려준다(D-122 — httpcore 공유 풀의 배정 겹침). TLS 설정(CA 묶음)은 하나를 함께 쓴다.
        ssl_context = httpx.create_ssl_context()
        pools: dict[tuple[str, float], UpstreamPool] = {}
        for u in upstreams.values():
            if (u.base_url, u.timeout) not in pools:
                pools[(u.base_url, u.timeout)] = UpstreamPool(partial(_connection, u.base_url, u.timeout, ssl_context),
                                                              s.max_connections, wait=5)
        app.state.upstreams = {api: UpstreamClient(pools[(u.base_url, u.timeout)], u.key) for api, u in upstreams.items()}
        app.state.metrics = Metrics()
        app.state.audit = AuditLog(s.log_path, s.log_max_bytes, s.log_backups, on_write=app.state.metrics.observe)
        app.state.ratelimit = RateLimiter(s.rate_per_minute)
        app.state.policies = s.policy_settings()
        app.state.chains = {name: build_chain(p, registry) for name, p in app.state.policies.items()}   # 정책마다 체인(D-119)
        app.state.chain = app.state.chains["default"]
        masks = any(isinstance(d, PIIDetector) and d.mode == "mask" for c in app.state.chains.values() for d in c.detectors)
        if masks and len(s.surrogate_key) < 32:
            raise RuntimeError(t("no_surrogate_key", s.lang))
        # 무거운 준비는 여기서 끝낸다. 실패하면 기동을 실패시킨다 — 준비 안 된 검사기를 달고 뜨면 방어가 꺼진 채로 돈다.
        for chain in app.state.chains.values():
            await chain.prepare()
        try:
            yield
        finally:
            for chain in app.state.chains.values():
                await chain.aclose()
            for pool in pools.values():
                await pool.aclose()
            app.state.audit.close()

    # 기본 문서 경로를 끈다(D-124): /docs·/redoc은 CDN 스크립트를 읽는 HTML이고 /openapi.json은 관리 경로까지 나열한다 — 허용 목록 밖이다(D-109)
    # 끝 '/' 경로도 307로 돌리지 않고 404다(D-124) — 307이면 감사 줄이 사유 없는 '그대로 전달'로 세어지고 Location이 Host 헤더를 따른다
    app = FastAPI(title="LLM Security Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.add_exception_handler(Exception, _unhandled)
    app.add_exception_handler(HTTPException, _http_error)
    app.middleware("http")(_audit_middleware)
    app.include_router(router)
    return app


def _connection(base_url: str, timeout: float, ssl_context: ssl.SSLContext) -> httpx.AsyncClient:
    """상류 연결 하나(D-122 — UpstreamPool이 빌려준다). 쿠키는 저장하지도 보내지도 않는다(D-109): 상류가 한 요청에 준 set-cookie
    (Cloudflare __cf_bm 등)가 다른 클라이언트의 요청에 붙어 나가면 안 된다. 쉬는 연결은 4초 뒤 버린다 — 상류 서버의 keep-alive(uvicorn·Node 기본
    5초)보다 짧아야 서버가 닫는 순간 그 연결로 보내 502가 나는 일이 없다(부하 측정에서 재현)."""
    return httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(connect=5, read=timeout, write=30, pool=5), verify=ssl_context,
                             limits=httpx.Limits(max_connections=1, max_keepalive_connections=1, keepalive_expiry=4),
                             cookies=CookieJar(DefaultCookiePolicy(allowed_domains=[])))


async def _unhandled(request: Request, exc: Exception) -> Response:
    """처리 중 예외 → 500. 감사 줄은 미들웨어가 이미 남겼고, 같은 요청 ID를 헤더에 붙여 대조할 수 있게 한다(D-102).
    예전에는 Starlette 기본 500(본문 텍스트, 헤더 없음)이 나가 감사 줄과 응답을 이을 길이 없었다.
    Starlette는 이 응답을 보낸 뒤 예외를 그대로 다시 올리므로 uvicorn 로그에는 예전처럼 남는다.
    본문에 예외 메시지는 넣지 않는다 — 요청 본문 조각이 섞이는 라이브러리가 흔하다.
    """
    response = error_format_for(request.url.path).error(500, "internal gateway error", "server_error", "internal_error")   # 그 API의 형식(D-122)
    rid = getattr(request.state, "request_id", None)
    if rid:
        response.headers["X-Gateway-Request-Id"] = rid
    return response


async def _http_error(request: Request, exc: Exception) -> Response:
    """허용 목록 밖의 경로·메서드(D-109) — 상류에 연결하지 않고 그 API의 오류 형식 404로 답한다.
    405도 404로 돌려준다: 어떤 메서드가 있는지 알리지 않는다."""
    assert isinstance(exc, HTTPException)       # HTTPException에만 등록한다
    if exc.status_code in (404, 405):
        request.state.upstream_error = "not_found"     # 감사 사유(D-124)
        return _not_found(request)
    return await http_exception_handler(request, exc)


def _not_found(request: Request) -> Response:
    return error_format_for(request.url.path).error(404, "not found", "not_found_error", "not_found")


async def _audit_middleware(request: Request, call_next):
    """요청 1건마다 JSONL 1줄. 지연을 세 갈래로 쪼개 기록한다."""
    state = request.state
    state.request_id = uuid.uuid4().hex[:16]
    state.upstream_ms = None   # 타겟 호출에 쓴 시간 (passthrough가 채운다)
    state.req_bytes = None
    state.req_digest = None
    state.blocked = False      # EVAL 3.3 자동 판정용. 검사기 체인이 채운다.
    state.chain_result = None
    state.response_steps = []
    state.session = None
    state.upstream_error = None  # 상류 호출 실패를 OpenAI 형식 응답으로 바꿨을 때의 예외 타입 이름
    state.upstream_request_id = None  # 상류가 준 요청 ID(D-109) — 클라이언트에는 넘기지 않고 감사에만 남긴다
    state.streaming = False      # 스트리밍 응답이면 감사 줄은 응답 생성기가 스트림 끝에서 쓴다(D-106)
    state.client = None          # 인증된 클라이언트 키의 이름(D-107 A). 무인증·실패면 None
    state.api = None             # 어댑터 이름(D-107 C). /v1/models는 "models", 404 등은 None
    state.policy = None          # 클라이언트의 정책 이름(D-119). 무인증이면 default, 인증 전 거절은 None
    state.model = None           # 요청의 model(D-120)
    state.usage = None           # 상류가 준 토큰 사용량(D-120)

    t0 = state.t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except BaseException as exc:   # 클라이언트가 끊으면 CancelledError(D-122) — 그 요청도 한 줄
        if state.streaming:
            # 스트림 응답을 만들었는데 응답이 돌기 전에 끝났다 — 스트림의 마무리(상류 닫기·볼트 해제·감사 한 줄)를 대신 부른다. 두 번 돌지 않는다
            with anyio.CancelScope(shield=True):
                await state.stream_finish(type(exc).__name__)
            raise
        # ★ 2026-09-22: 이 자리가 비어 있었다. 기록이 처리 **완료 후에만** 이뤄져서,
        # 처리 중 예외가 나면 거기 도달하지 못했다. 타겟 연결 오류를 일으키면
        # HTTP 500이 나가고 **감사 로그는 0줄**이었다 — "요청 1건당 1줄"이라는
        # 설계 의도와 다르고, 장애 요청이 평가·운영 기록에서 통째로 빠진다.
        #
        # 남기는 것은 예외 **타입 이름뿐**이다. 메시지에는 요청 본문 조각이 섞여
        # 들어오는 라이브러리가 흔하다 — 본문을 안 남긴다는 규칙이 뒷문으로 깨진다.
        try:
            if not request.url.path.startswith(INTERNAL_PREFIX):
                request.app.state.audit.write(record(
                    request, None, (time.perf_counter() - t0) * 1000,
                    error=type(exc).__name__))
        except Exception:
            pass          # 기록 실패가 원래 예외를 가리지 않게 한다
        raise
    total_ms = (time.perf_counter() - t0) * 1000

    response.headers["X-Gateway-Request-Id"] = state.request_id

    if request.url.path.startswith(INTERNAL_PREFIX) or state.streaming:
        return response

    request.app.state.audit.write(record(request, response, total_ms, error=None))
    return response


def _is_admin(request: Request) -> bool:
    """관리 키(D-109). 없으면 아무도 관리자가 아니다."""
    key = request.app.state.settings.admin_key
    auth = request.headers.get("authorization", "")
    return bool(key) and auth[:7].lower() == "bearer " and hmac.compare_digest(auth[7:].strip().encode(), key.encode())


@router.get("/__gateway/health")
async def health() -> dict:
    """살아 있는가만 답한다. 인증이 없으므로 구성은 싣지 않는다(D-109) — 상세는 /__gateway/info."""
    return {"status": "ok"}


@router.get("/__gateway/info")
async def info(request: Request) -> Response:
    """실행 중인 버전·코드 지문·상류·검사기. 관리 키가 있어야 보인다(D-109)."""
    if not _is_admin(request):
        return _not_found(request)
    s: Settings = request.app.state.settings
    return JSONResponse({
        "version": VERSION,
        "code": code_fingerprint(),
        "config": s.config_version,                                     # 설정 파일 SHA-256 앞 12자(D-119), 없으면 null
        "target": s.target_url,
        "upstreams": {api: s.upstream(api).base_url for api in API_NAMES},   # 공급자 키는 싣지 않는다
        "detectors": list(request.app.state.chain.names),
        "policies": {name: list(chain.names) for name, chain in request.app.state.chains.items()},
    })


def _gauges(request: Request) -> tuple[dict[str, int], dict[str, int]]:
    """D-122: 503을 정하는 두 양 — 정책마다의 대체값 세션(상한 2,000 → gateway_busy), 상류마다 빌려 간 연결(상한 GATEWAY_MAX_CONNECTIONS → upstream_busy).
    주소가 같은 풀이 여럿이면(API마다 시간 제한이 다르면) 합이 아니라 가장 바쁜 풀의 값이다 — 상한이 풀마다라서 같은 단위다(D-124)."""
    sessions = {name: sum(d.vault.session_count for d in chain.detectors if isinstance(d, PIIDetector) and d.mode == "mask")
                for name, chain in request.app.state.chains.items()}
    in_use: dict[str, int] = {}
    for up in {id(u.pool): u for u in request.app.state.upstreams.values()}.values():   # 같은 풀을 여러 API가 함께 쓴다
        in_use[up.pool.base_url] = max(in_use.get(up.pool.base_url, 0), up.pool.in_use)
    return sessions, in_use


@router.get("/__gateway/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus 텍스트 형식(D-107 E). 감사 레코드에서 센 값이라 감사 줄과 어긋나지 않는다. 관리 키가 있어야 보인다(D-109)."""
    if not _is_admin(request):
        return _not_found(request)
    return Response(request.app.state.metrics.render(*_gauges(request)), media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/__gateway/stats")
async def stats(request: Request) -> Response:
    """대시보드의 데이터(D-124) — 이 프로세스의 누적과 최근 200줄. 관리 키 Bearer만(키를 URL·Basic으로 받지 않는다), 아니면 404.
    수집용이 아니다(형식이 바뀔 수 있다) — 수집은 metrics로 한다."""
    if not _is_admin(request):
        return _not_found(request)
    body = request.app.state.metrics.snapshot(*_gauges(request), request.app.state.settings.max_connections)
    return JSONResponse(body, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/__gateway/dashboard")
async def dashboard(request: Request) -> Response:
    """운영 대시보드(D-124) — 정적 HTML. 관리 키가 설정된 게이트웨이에만 있다(없으면 404). 인증 없이 주는 것은 데이터·키·버전이 없는 화면뿐이다 —
    주소창 이동으로는 Bearer 헤더를 실을 수 없으므로, 화면의 스크립트가 탭에 넣은 키로 /__gateway/stats를 읽는다."""
    if not request.app.state.settings.admin_key:
        return _not_found(request)
    return Response(DASHBOARD, media_type="text/html; charset=utf-8", headers=DASHBOARD_HEADERS)


def _admit(request: Request) -> Response | None:
    """키 검증(401)과 레이트리밋(429). 본문을 읽기 전에 거른다 — 틀린 키의 본문은 읽지도, 검사하지도, 중계하지도 않는다(D-107 A)."""
    auth: Auth = request.app.state.auth
    client = auth.client_of(request.headers)
    request.state.client = client.name if client else None
    # 무인증이면 default, 인증에 실패한 요청은 정책이 없다(None) — 감사·대시보드 줄에 정책이 찍히지 않게(D-124)
    request.state.policy = client.policy if client else (None if auth.enabled else "default")
    if auth.enabled and client is None:
        request.state.upstream_error = "unauthorized"
        return error_format_for(request.url.path).error(401, "invalid or missing API key", "authentication_error", "invalid_api_key")
    # 레이트리밋(D-107 E): 클라이언트 이름(무인증이면 IP)마다 분당 상한.
    ok, retry_after = request.app.state.ratelimit.allow(
        request.state.client or (request.client.host if request.client else "?"))
    if not ok:
        request.state.upstream_error = "rate_limited"
        response = error_format_for(request.url.path).error(429, "rate limit exceeded", "rate_limit_error", "rate_limit_exceeded")
        response.headers["retry-after"] = str(retry_after)
        return response
    return None


@router.post("/v1/chat/completions")
@router.post("/v1/responses")
@router.post("/v1/messages")
async def api(request: Request) -> Response:
    if (denied := _admit(request)) is not None:
        return denied
    body, size = await read_body(request, request.app.state.settings.max_body_bytes)
    request.state.req_bytes = size
    if body is None:
        # 상류도 검사기도 부르지 않는다. 감사 줄은 미들웨어가 413으로 남긴다.
        request.state.upstream_error = "request_too_large"
        return error_format_for(request.url.path).error(
            413, f"request body exceeds {request.app.state.settings.max_body_bytes} bytes", "invalid_request_error", "request_too_large")
    request.state.req_digest = digest(body)

    # D-107 C: 어댑터가 본문을 한 번 파싱한다. 검사기는 그 doc를 본다.
    adapter = adapter_for(request.url.path)
    assert adapter is not None                  # 라우트가 어댑터가 있는 세 경로만 받는다
    request.state.api = adapter.name
    try:
        doc = Doc(adapter, adapter.parse(body))
    except ApiError as exc:
        request.state.upstream_error = exc.code         # invalid_json·invalid_messages·invalid_request·invalid_stream — 감사 사유(D-124)
        return adapter.error(exc.status, str(exc), exc.type_, exc.code, exc.param)
    request.state.model = adapter.model(doc.payload) if isinstance(doc.payload.get("model"), str) else None   # 서로게이트는 '?'(D-124)

    policy: Settings = request.app.state.policies[request.state.policy]
    if policy.allowed_models is not None:       # 허용 모델(D-119) — 검사기·상류를 부르지 않는다
        model = adapter.model(doc.payload)
        if not any(fnmatch.fnmatchcase(model, pattern) for pattern in policy.allowed_models):
            request.state.upstream_error = "model_not_allowed"
            return adapter.error(403, f"model not allowed: {model!r}", "permission_error", "model_not_allowed")
    request.state.upstream = request.app.state.upstreams[adapter.name]
    chain = request.app.state.chains[request.state.policy]
    # 볼트는 요청 단위다(D-107 A). 클라이언트가 보낸 sessionId는 키가 아니다 — 그것을 맞추면 남의 원문을
    # 꺼낼 수 있었다(D-107 §1 #1). 다음 턴 이력의 원문은 다시 가려지므로(D-099) 대화 간 상태가 필요 없다.
    session = request.state.session = request.state.request_id
    try:
        return await relay(request, body, doc, chain, session)
    finally:
        # 응답이 나가면 매핑을 다시 쓸 일이 없다 — 차단·상류 오류·예외·클라이언트 끊김으로 끝나도 바로 버린다(끊김의 취소를 막고, D-122).
        # 스트리밍 응답은 스트림이 끝난 뒤 생성기가 해제한다(D-106): 여기서 먼저 버리면 조각을 복원할 원문이 없다.
        if not request.state.streaming:
            with anyio.CancelScope(shield=True):
                await chain.release(session)


@router.get("/v1/models")
async def models(request: Request) -> Response:
    """모델 목록(D-109). 본문이 없으므로 검사기를 거치지 않고 키 검증·레이트리밋·헤더 허용 목록만 지나 중계한다."""
    if (denied := _admit(request)) is not None:
        return denied
    request.state.api = "models"
    # Anthropic SDK는 anthropic-version을 보낸다 — Messages 쪽 상류의 목록을 준다(D-119)
    request.state.upstream = request.app.state.upstreams["messages" if "anthropic-version" in request.headers else "chat"]
    upstream = await send(request, "/v1/models", None)
    if not isinstance(upstream, httpx.Response):
        return upstream
    content = await read_capped(request, upstream)
    return downstream(upstream, content) if isinstance(content, bytes) else content


app = create_app(Settings.from_env())
