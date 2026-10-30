"""LLM Security Gateway — 세 API(Chat Completions·Responses·Messages)의 검사 프록시.

요청: 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 어댑터 파싱(400) → 검사기 체인(인젝션 → PII) → 상류.
응답: 대체값 복원(스트리밍은 조각 경계·채널별, gateway/streaming.py) → 감사 한 줄(원문 없음).

D-107 A: 클라이언트 키 인증(GATEWAY_CLIENT_KEYS, 없으면 기동 실패 — GATEWAY_AUTH=off로만 연다)과 상류 키 보관
     (GATEWAY_UPSTREAM_KEY). 볼트는 요청 단위다 — 응답(스트림)이 끝나면 버린다.
D-109: 경로 허용 목록 — 세 POST와 GET /v1/models만 받고 그 밖은 404(상류에 연결하지 않는다). 요청·응답 헤더도 허용 목록.
     /__gateway/health는 status만, 상세(info)와 metrics는 GATEWAY_ADMIN_KEY가 있어야 보인다.
"""
from __future__ import annotations

import hmac
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException

from gateway.api import ApiError, Doc, adapter_for, error_format_for
from gateway.audit import AuditLog, digest, utcnow
from gateway.auth import Auth, parse_client_keys
from gateway.chain import ChainResult, DetectorChain, Step
from gateway.detectors.base import Detector, Inspection
from gateway.detectors.injection import InjectionRuleDetector
from gateway.detectors.pii import ALL_KINDS, PIIDetector
from gateway.metrics import Metrics
from gateway.openai_api import PII_ROLES
from gateway.ratelimit import RateLimiter
from gateway.streaming import StreamRestorer
from gateway.vault import TokenVault, VaultFull
from gateway.version import VERSION, code_fingerprint

load_dotenv()  # .env를 읽되, 이미 설정된 환경변수는 덮어쓰지 않는다

# 상류 주소. 기본값 8000은 로컬 스텁·OpenAI 호환 서버용이다.
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8000").rstrip("/")
TARGET_TIMEOUT = float(os.environ.get("GATEWAY_TIMEOUT", "600"))  # D-023: 긴 생성 대비
# D-086: TARGET_URL은 origin이다. chat completions만 상류 경로를 바꿀 수 있다 — Gemini의 OpenAI 호환
# 엔드포인트는 /v1beta/openai/chat/completions라 "origin + 받은 경로"로는 맞출 수 없다(D-085 §3).
# 기본값은 받은 경로와 같다 = 기존 동작. 다른 경로는 건드리지 않는다.
CHAT_UPSTREAM_PATH = os.environ.get("GATEWAY_CHAT_UPSTREAM_PATH", "/v1/chat/completions")
AUDIT_LOG_PATH = os.environ.get("GATEWAY_LOG_PATH", "logs/gateway.jsonl")     # `-`면 stdout(D-107 E)
AUDIT_LOG_MAX_BYTES = int(os.environ.get("GATEWAY_LOG_MAX_BYTES", str(100 * 1024 * 1024)))
AUDIT_LOG_BACKUPS = int(os.environ.get("GATEWAY_LOG_BACKUPS", "5"))
RATE_PER_MINUTE = int(os.environ.get("GATEWAY_RATE_PER_MINUTE", "0"))        # 0 = 끔(D-107 E)

# 게이트웨이 자체 경로. 감사 로그에서 제외한다 — 헬스체크가 초당 여러 번 때리면 지연 통계가 오염된다.
INTERNAL_PREFIX = "/__gateway/"
# D-109: info·metrics를 여는 관리 키(Bearer). 없으면 둘 다 404다.
ADMIN_KEY = os.environ.get("GATEWAY_ADMIN_KEY", "")

# 차단 시 사용자에게 돌려줄 문구. 어댑터가 그 API의 정상 응답 모양(HTTP 200)에 싣는다 — 클라이언트 SDK가 오류로 다루지 않는다.
# 차단 여부는 HTTP 코드가 아니라 gateway_blocked 필드와 감사 로그로 판별한다.
BLOCKED_MESSAGE = os.environ.get(
    "GATEWAY_BLOCKED_MESSAGE", "요청이 보안 정책에 의해 차단되었습니다.")

# D-099: 본문 크기 상한. 상한이 없으면 큰 요청 하나가 메모리와 검사기 시간을 독차지하고,
# 워커가 1개라 그동안 다른 요청이 전부 멈춘다. 이미지 첨부처럼 큰 요청을 받으려면 값을 올린다
# (OpenAI 경로의 검사기는 text 파트만 보므로 이미지 크기는 검사 시간에 들어가지 않는다).
MAX_BODY_BYTES = int(os.environ.get("GATEWAY_MAX_BODY_BYTES", str(1024 * 1024)))
# D-110: 가용성 상한. 탐지 건수(mask 모드, 넘으면 413), 상류 연결 풀(넘쳐 5초 기다리면 503), 비스트리밍 상류 응답(넘으면 502).
MAX_FINDINGS = int(os.environ.get("GATEWAY_MAX_FINDINGS", "5000"))
# D-111: 결정적 대체값의 키. mask 모드면 필수(32자 이상) — `python -m gateway keygen` 출력을 그대로 써도 된다.
# 이 키와 대체값이 있으면 원문을 되짚을 수 있으므로(전화번호 공간은 작다) 클라이언트 키·공급자 키와 같은 등급으로 보관한다.
SURROGATE_KEY = os.environ.get("GATEWAY_SURROGATE_KEY", "")
MAX_CONNECTIONS = int(os.environ.get("GATEWAY_MAX_CONNECTIONS", "100"))
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
UPSTREAM_TIMEOUT = httpx.Timeout(connect=5, read=TARGET_TIMEOUT, write=30, pool=5)

# D-107 A: 인증. 키 목록이 없으면 lifespan에서 기동을 실패시킨다 — 보안 제품은 닫힌 채로 시작한다.
# 무인증은 GATEWAY_AUTH=off로 명시한 로컬 실험에서만. 상류 키가 있으면 클라이언트의 인증 헤더를 떼고 상류 형식으로 단다.
AUTH_OFF = os.environ.get("GATEWAY_AUTH", "").strip().lower() == "off"
CLIENT_KEYS_SPEC = os.environ.get("GATEWAY_CLIENT_KEYS", "")
AUTH = Auth(None if AUTH_OFF else parse_client_keys(CLIENT_KEYS_SPEC) or None,
            os.environ.get("GATEWAY_UPSTREAM_KEY", ""))

# D-107 D: 제품 설정 세 개 — GATEWAY_INJECTION(observe 기본|block|off), GATEWAY_INJECTION_SCOPE(turn 기본|all), GATEWAY_PII(mask 기본|detect|off).
# 체인 순서는 고정이다: injection → pii.
# 저수준 목록 GATEWAY_DETECTORS(쉼표 구분)는 측정·테스트용으로 남긴다 — **설정돼 있으면 그것이 우선**이고, 빈 문자열은 검사기 없음(4-A)이다.
PII_KINDS = tuple(x.strip() for x in os.environ.get("GATEWAY_PII_KINDS", ",".join(ALL_KINDS)).split(",") if x.strip())


def pii_roles() -> frozenset[str]:
    """GATEWAY_PII_ROLES(쉼표) — 가리는 역할을 좁힌다(D-112). 기본은 전부. developer는 system의 별칭. 모르는 이름은 기동 실패."""
    spec = os.environ.get("GATEWAY_PII_ROLES")
    if spec is None:
        return PII_ROLES
    roles = frozenset({"developer": "system"}.get(x, x) for x in (y.strip().lower() for y in spec.split(",")) if x)
    if not roles or roles - PII_ROLES:
        raise ValueError(f"GATEWAY_PII_ROLES는 {sorted(PII_ROLES)}(developer = system) 중에서 고른다: {spec!r}")
    return roles


def detector_names_from_env() -> list[str]:
    spec = os.environ.get("GATEWAY_DETECTORS")
    if spec is not None:
        return [x.strip() for x in spec.split(",") if x.strip()]
    names: list[str] = []
    injection = os.environ.get("GATEWAY_INJECTION", "observe").strip().lower()
    scope = os.environ.get("GATEWAY_INJECTION_SCOPE", "turn").strip().lower()
    if injection == "observe":
        names.append("injection_observe")
    elif injection == "block":
        names.append("injection_rule" if scope == "all" else "injection_rule_turn")
    elif injection != "off":
        raise ValueError(f"GATEWAY_INJECTION은 observe|block|off 중 하나여야 한다: {injection!r}")
    if scope not in ("turn", "all"):
        raise ValueError(f"GATEWAY_INJECTION_SCOPE는 turn|all 중 하나여야 한다: {scope!r}")
    pii = os.environ.get("GATEWAY_PII", "mask").strip().lower()
    if pii in ("mask", "detect"):
        names.append("pii_mask" if pii == "mask" else "pii")
    elif pii != "off":
        raise ValueError(f"GATEWAY_PII는 mask|detect|off 중 하나여야 한다: {pii!r}")
    return names


# 이름 → 생성자. 테스트는 tests/chain_app.py에서 시험용 검사기를 더한다.
DETECTOR_REGISTRY: dict[str, Callable[[], Detector]] = {
    "pii": lambda: PIIDetector("detect", kinds=PII_KINDS, roles=pii_roles()),
    # 볼트 TTL은 상류 타임아웃보다 길다 — 긴 스트림 도중 매핑이 만료되면 복원이 깨진다(D-110).
    "pii_mask": lambda: PIIDetector("mask", kinds=PII_KINDS, max_findings=MAX_FINDINGS, roles=pii_roles(),
                                    vault=TokenVault(ttl=TARGET_TIMEOUT + 60, key=SURROGATE_KEY.encode() or None)),
    "injection_observe": lambda: InjectionRuleDetector(mode="observe"),
    "injection_rule": lambda: InjectionRuleDetector(),
    "injection_rule_turn": lambda: InjectionRuleDetector(scope="turn"),
}


def build_chain(names: list[str] | None = None) -> DetectorChain:
    names = detector_names_from_env() if names is None else names
    unknown = [n for n in names if n not in DETECTOR_REGISTRY]
    if unknown:
        raise ValueError(f"알 수 없는 검사기: {unknown}. 등록된 것: {sorted(DETECTOR_REGISTRY)}")
    return DetectorChain([DETECTOR_REGISTRY[n]() for n in names])

# D-109: 클라이언트에 넘기는 상류 응답 헤더. 그 밖(set-cookie·openai-organization·레이트리밋·요청 ID·hop-by-hop·
# content-encoding·content-length·date·server)은 전부 뗀다. 요청 헤더의 허용 목록은 gateway/auth.py에 있다.
PASS_RESPONSE_HEADERS = frozenset({"content-type", "cache-control", "retry-after", "retry-after-ms", "x-should-retry"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 수명 동안 클라이언트 1개만 두고 연결을 재사용한다.
    # 요청마다 새로 만들면 매번 TCP 핸드셰이크 → EVAL 4절 p95 목표를 혼자 다 까먹는다.
    if not CHAT_UPSTREAM_PATH.startswith("/"):
        raise RuntimeError(f"GATEWAY_CHAT_UPSTREAM_PATH는 /로 시작하는 경로여야 한다: {CHAT_UPSTREAM_PATH!r}")
    if not AUTH.enabled and not AUTH_OFF:
        raise RuntimeError("GATEWAY_CLIENT_KEYS가 없다 — 클라이언트 키 없이는 기동하지 않는다(D-107 A). "
                           "`python -m gateway keygen`으로 키를 만들어 넣거나, 로컬 실험이면 GATEWAY_AUTH=off를 명시한다")
    if AUTH_OFF and AUTH.upstream_key:
        raise RuntimeError("GATEWAY_AUTH=off와 GATEWAY_UPSTREAM_KEY를 함께 쓸 수 없다 — 누구나 상류 키로 중계하게 된다(D-109)")
    app.state.auth = AUTH
    # 쿠키는 저장하지도 보내지도 않는다(D-109). 클라이언트는 모든 요청이 함께 쓴다 — 기본 쿠키 저장소면 상류가 한 요청에 준
    # set-cookie(Cloudflare __cf_bm 등)가 다른 클라이언트의 요청에 붙어 나간다(재현: 스텁 /v1/models 두 번).
    app.state.client = httpx.AsyncClient(base_url=TARGET_URL, timeout=UPSTREAM_TIMEOUT,
                                         limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
                                         cookies=CookieJar(DefaultCookiePolicy(allowed_domains=[])))
    app.state.metrics = Metrics()
    app.state.audit = AuditLog(AUDIT_LOG_PATH, AUDIT_LOG_MAX_BYTES, AUDIT_LOG_BACKUPS, on_write=app.state.metrics.observe)
    app.state.ratelimit = RateLimiter(RATE_PER_MINUTE)
    app.state.chain = build_chain()
    if any(isinstance(d, PIIDetector) and d.mode == "mask" for d in app.state.chain.detectors) and len(SURROGATE_KEY) < 32:
        raise RuntimeError("GATEWAY_SURROGATE_KEY가 없거나 32자보다 짧다 — PII mask 모드는 결정적 대체값 키가 필요하다(D-111). "
                           "`python -m gateway keygen`으로 만들어 넣는다")
    # 무거운 준비는 여기서 끝낸다. 실패하면 기동을 실패시킨다 — 준비 안 된 검사기를 달고 뜨면 방어가 꺼진 채로 돈다.
    await app.state.chain.prepare()
    try:
        yield
    finally:
        await app.state.chain.aclose()
        await app.state.client.aclose()
        app.state.audit.close()


app = FastAPI(title="LLM Security Gateway", lifespan=lifespan)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> Response:
    """처리 중 예외 → 500. 감사 줄은 미들웨어가 이미 남겼고, 같은 요청 ID를 헤더에 붙여 대조할 수 있게 한다(D-102).
    예전에는 Starlette 기본 500(본문 텍스트, 헤더 없음)이 나가 감사 줄과 응답을 이을 길이 없었다.
    Starlette는 이 응답을 보낸 뒤 예외를 그대로 다시 올리므로 uvicorn 로그에는 예전처럼 남는다.
    본문에 예외 메시지는 넣지 않는다 — 요청 본문 조각이 섞이는 라이브러리가 흔하다.
    """
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=500, headers={"X-Gateway-Request-Id": rid} if rid else None,
                        content={"error": {"message": "internal gateway error", "type": "server_error",
                                           "param": None, "code": "internal_error"}})


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException) -> Response:
    """허용 목록 밖의 경로·메서드(D-109) — 상류에 연결하지 않고 그 API의 오류 형식 404로 답한다.
    405도 404로 돌려준다: 어떤 메서드가 있는지 알리지 않는다."""
    if exc.status_code in (404, 405):
        return _not_found(request)
    return await http_exception_handler(request, exc)


def _not_found(request: Request) -> Response:
    return error_format_for(request.url.path).error(404, "not found", "not_found_error", "not_found")


@app.middleware("http")
async def audit(request: Request, call_next):
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

    t0 = state.t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # ★ 2026-09-22: 이 자리가 비어 있었다. 기록이 처리 **완료 후에만** 이뤄져서,
        # 처리 중 예외가 나면 거기 도달하지 못했다. 타겟 연결 오류를 일으키면
        # HTTP 500이 나가고 **감사 로그는 0줄**이었다 — "요청 1건당 1줄"이라는
        # 설계 의도와 다르고, 장애 요청이 평가·운영 기록에서 통째로 빠진다.
        #
        # 남기는 것은 예외 **타입 이름뿐**이다. 메시지에는 요청 본문 조각이 섞여
        # 들어오는 라이브러리가 흔하다 — 본문을 안 남긴다는 규칙이 뒷문으로 깨진다.
        try:
            if not request.url.path.startswith(INTERNAL_PREFIX):
                request.app.state.audit.write(_audit_record(
                    request, None, (time.perf_counter() - t0) * 1000,
                    error=type(exc).__name__))
        except Exception:
            pass          # 기록 실패가 원래 예외를 가리지 않게 한다
        raise
    total_ms = (time.perf_counter() - t0) * 1000

    response.headers["X-Gateway-Request-Id"] = state.request_id

    if request.url.path.startswith(INTERNAL_PREFIX) or state.streaming:
        return response

    request.app.state.audit.write(_audit_record(request, response, total_ms, error=None))
    return response


def _audit_record(request: Request, response: Response | None,
                  total_ms: float, error: str | None, res_bytes: int | None = None) -> dict:
    """감사 로그 한 줄. 예외로 끝난 요청도 **같은 모양으로** 남긴다.

    모양이 갈리면 집계 도구가 한쪽을 조용히 빠뜨린다 — 그게 이 프로젝트가
    FPR 집계기에서 이미 겪은 실패다(D-064).
    `res_bytes`는 스트리밍 응답처럼 content-length가 없을 때 호출자가 센 값이다(D-106).
    """
    state = request.state
    upstream_ms = getattr(state, "upstream_ms", None)
    return {
        "ts": utcnow(),
        "request_id": state.request_id,
        "method": request.method,
        "path": request.url.path,
        # ★ 2026-09-22: 예전에는 쿼리 문자열을 원문 그대로 남겼다. 본문과 Authorization
        # 헤더는 안 남기면서 URL은 보호 밖이었다 — URL에 개인정보나 토큰이 실리면 그대로
        # 기록된다. 본문에 이미 쓰는 규칙("원문은 남기지 않는다, 크기와 지문만")을
        # URL에도 적용하되, **키 이름은 남긴다**: "URL에 token이 실려 왔다"는 사실은
        # 운영에 필요하고, 위험한 것은 값이다.
        "query_keys": _query_keys(request.url.query),
        "query_bytes": len(request.url.query),
        # 예외로 끝난 요청은 상위 미들웨어가 500으로 바꾼다. 그 사실을 그대로 적는다.
        "status": response.status_code if response is not None else 500,
        "error": error or getattr(state, "upstream_error", None),
        # EVAL 4절: 종단 지연 / 타겟 호출 / 게이트웨이 내부 처리를 분리한다.
        "total_ms": round(total_ms, 2),
        "upstream_ms": None if upstream_ms is None else round(upstream_ms, 2),
        "gateway_ms": round(total_ms - (upstream_ms or 0.0), 2),
        # 본문 원문은 남기지 않는다. 크기와 지문만.
        "req_bytes": getattr(state, "req_bytes", None),
        "req_sha256_12": getattr(state, "req_digest", None),
        "res_bytes": res_bytes if res_bytes is not None else (
            _int_or_none(response.headers.get("content-length")) if response is not None else None),
        "blocked": getattr(state, "blocked", False),
        "client": getattr(state, "client", None),          # 키 이름(D-107 A). 예전에는 IP였다 — 이제 `ip`
        "ip": request.client.host if request.client else None,
        "api": getattr(state, "api", None),                # chat | messages | responses | models | null (D-107 C·D-109)
        "upstream_request_id": getattr(state, "upstream_request_id", None),
        **_pii_fields(getattr(state, "response_steps", [])),
        **_chain_fields(getattr(state, "chain_result", None)),
        "response_detectors": [s.as_dict() for s in getattr(state, "response_steps", [])],
    }


def _pii_fields(steps: list[Step]) -> dict:
    """복원 가시화(D-113): 발급·복원·의심 잔여를 감사 줄 맨 위에 둔다 — 집계가 response_detectors를 뒤지지 않게."""
    meta = next((s.meta for s in steps if s.detector == "pii_mask"), {})
    return {"pii_issued": meta.get("issued", 0), "pii_restored": meta.get("restored", 0), "pii_suspect": meta.get("suspect", 0)}


def _int_or_none(v: str | None) -> int | None:
    return int(v) if v is not None and v.isdigit() else None


def _query_keys(query: str) -> list[str]:
    """쿼리 파라미터의 **이름만** 정렬해 돌려준다. 값은 담지 않는다.

    `parse_qsl`을 쓰지 않는 이유: 값이 잠깐이라도 중간 자료구조에 들어가는 경로를
    만들지 않는다. 여기서는 '='의 앞부분만 본다. 중복 이름은 한 번만 센다.
    """
    keys = set()
    for part in query.split("&"):
        if not part:
            continue
        name = unquote(part.split("=", 1)[0])
        if name:
            keys.add(name)
    return sorted(keys)


def _chain_fields(result: ChainResult | None) -> dict:
    """검사기 체인 실행 내역. EVAL 4절이 요구하는 단계별 소요 시간을 남긴다."""
    if result is None:
        return {"chain_ms": None, "detectors": [], "blocked_by": None, "transformed": False}
    return {
        "chain_ms": result.chain_ms,
        "detectors": [s.as_dict() for s in result.steps],
        "blocked_by": result.blocked_by,
        "transformed": result.transformed,
    }


def _is_admin(request: Request) -> bool:
    """관리 키(D-109). 없으면 아무도 관리자가 아니다."""
    auth = request.headers.get("authorization", "")
    return bool(ADMIN_KEY) and auth[:7].lower() == "bearer " and hmac.compare_digest(auth[7:].strip().encode(), ADMIN_KEY.encode())


@app.get("/__gateway/health")
async def health() -> dict:
    """살아 있는가만 답한다. 인증이 없으므로 구성은 싣지 않는다(D-109) — 상세는 /__gateway/info."""
    return {"status": "ok"}


@app.get("/__gateway/info")
async def info(request: Request) -> Response:
    """실행 중인 버전·코드 지문·상류·검사기. 관리 키가 있어야 보인다(D-109)."""
    if not _is_admin(request):
        return _not_found(request)
    return JSONResponse({
        "version": VERSION,
        "code": code_fingerprint(),
        "target": TARGET_URL,
        "chat_upstream_path": CHAT_UPSTREAM_PATH,
        "detectors": list(request.app.state.chain.names),
    })


@app.get("/__gateway/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus 텍스트 형식(D-107 E). 감사 레코드에서 센 값이라 감사 줄과 어긋나지 않는다. 관리 키가 있어야 보인다(D-109)."""
    if not _is_admin(request):
        return _not_found(request)
    return Response(request.app.state.metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")


def _admit(request: Request) -> Response | None:
    """키 검증(401)과 레이트리밋(429). 본문을 읽기 전에 거른다 — 틀린 키의 본문은 읽지도, 검사하지도, 중계하지도 않는다(D-107 A)."""
    auth: Auth = request.app.state.auth
    request.state.client = auth.client_of(request.headers)
    if auth.enabled and request.state.client is None:
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


@app.post("/v1/chat/completions")
@app.post("/v1/responses")
@app.post("/v1/messages")
async def api(request: Request) -> Response:
    if (denied := _admit(request)) is not None:
        return denied
    body, size = await _read_body(request)
    request.state.req_bytes = size
    if body is None:
        # 상류도 검사기도 부르지 않는다. 감사 줄은 미들웨어가 413으로 남긴다.
        return error_format_for(request.url.path).error(
            413, f"request body exceeds {MAX_BODY_BYTES} bytes", "invalid_request_error", "request_too_large")
    request.state.req_digest = digest(body)

    # D-107 C: 어댑터가 본문을 한 번 파싱한다. 검사기는 그 doc를 본다.
    adapter = adapter_for(request.url.path)
    request.state.api = adapter.name
    try:
        doc = Doc(adapter, adapter.parse(body))
    except ApiError as exc:
        return adapter.error(exc.status, str(exc), exc.type_, exc.code, exc.param)

    chain = request.app.state.chain
    # 볼트는 요청 단위다(D-107 A). 클라이언트가 보낸 sessionId는 키가 아니다 — 그것을 맞추면 남의 원문을
    # 꺼낼 수 있었다(D-107 §1 #1). 다음 턴 이력의 원문은 다시 가려지므로(D-099) 대화 간 상태가 필요 없다.
    session = request.state.session = request.state.request_id
    try:
        return await _relay(request, body, doc, chain, session)
    finally:
        # 응답이 나가면 매핑을 다시 쓸 일이 없다 — 차단·상류 오류·예외로 끝나도 바로 버린다.
        # 스트리밍 응답은 스트림이 끝난 뒤 생성기가 해제한다(D-106): 여기서 먼저 버리면 조각을 복원할 원문이 없다.
        if not request.state.streaming:
            await chain.release(session)


@app.get("/v1/models")
async def models(request: Request) -> Response:
    """모델 목록(D-109). 본문이 없으므로 검사기를 거치지 않고 키 검증·레이트리밋·헤더 허용 목록만 지나 중계한다."""
    if (denied := _admit(request)) is not None:
        return denied
    request.state.api = "models"
    upstream = await _send(request, "/v1/models", None)
    if not isinstance(upstream, httpx.Response):
        return upstream
    content = await _read_capped(request, upstream)
    return _downstream(upstream, content) if isinstance(content, bytes) else content


async def _read_body(request: Request) -> tuple[bytes | None, int]:
    """(본문, 바이트 수). 상한을 넘으면 본문 대신 None.

    넘은 뒤에도 끝까지 읽어서 버린다 — 읽다 말고 응답하면 클라이언트가 413 대신 연결 오류를
    받는다. 버리는 동안 쌓지 않으므로 메모리는 상한까지만 쓴다.
    """
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size <= MAX_BODY_BYTES:
            chunks.append(chunk)
    return (b"".join(chunks) if size <= MAX_BODY_BYTES else None), size


async def _relay(request: Request, body: bytes, doc: Doc, chain: DetectorChain, session: str) -> Response:
    """검사기 체인 → (차단 또는) 상류 호출 → 응답 후처리."""
    adapter = doc.adapter
    try:
        result = await chain.run(Inspection(
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            headers=request.headers,
            body=body,
            session=session,
            doc=doc,
        ))
    except ApiError as exc:       # 탐지 상한(413, D-110) — 상류에 보내지 않는다
        request.state.upstream_error = exc.code
        return adapter.error(exc.status, str(exc), exc.type_, exc.code, exc.param)
    except VaultFull:             # 볼트 세션 상한 — 진행 중인 세션을 밀어내지 않고 새 요청을 거절한다(D-110)
        request.state.upstream_error = "gateway_busy"
        return _busy(adapter.error(503, "gateway is at capacity", "overloaded_error", "gateway_busy"))
    request.state.chain_result = result
    wants_stream = adapter.wants_stream(doc.payload)
    if result.blocked:
        request.state.blocked = True
        # 차단 시 상류를 호출하지 않는다 → upstream_ms는 None으로 남는다.
        # 차단 사유는 응답에 넣지 않는다(D-040). 요청 ID만 넣는다 — 사용자가 운영자에게 물을 수 있는 손잡이다(D-107 E).
        message = f"{BLOCKED_MESSAGE} (요청 ID: {request.state.request_id})"
        return adapter.blocked(doc.payload, request.state.request_id, message, wants_stream)

    upstream = await _send(request, adapter.upstream_path(), result.body)   # TRANSFORM이 있었으면 바뀐 본문
    if not isinstance(upstream, httpx.Response):
        return upstream
    if wants_stream and _is_sse(upstream):
        request.state.streaming = True
        return _stream_response(request, upstream, chain, session, adapter.stream_shape())

    # SSE가 아니면(비스트리밍, 상류 오류 JSON, 스트리밍을 무시하는 상류) 상한까지 읽어 비스트리밍 후처리로 보낸다(D-106·D-110).
    content = await _read_capped(request, upstream)
    if not isinstance(content, bytes):
        return content
    text = _as_text(content, upstream.headers.get("content-type", ""))
    if text is not None:
        restored, steps = await chain.run_response(session, text)
        if steps:
            request.state.response_steps = steps
        if restored != text:
            content = restored.encode("utf-8")
    response = _downstream(upstream, content)
    pii = _pii_fields(request.state.response_steps)
    if pii["pii_issued"]:
        response.headers["x-gateway-pii"] = f"issued={pii['pii_issued']} restored={pii['pii_restored']}"
    return response


async def _send(request: Request, path: str, body: bytes | None) -> httpx.Response | Response:
    """상류 호출. 헤더는 허용 목록만(D-109, auth.upstream_headers). 머리만 받고 본문은 열어 둔다 — 호출자가 SSE면 흘려보내고
    아니면 `_read_capped`로 읽는다. 실패는 그 API의 오류 형식 응답으로 바꿔 돌려준다(D-086·D-110)."""
    client: httpx.AsyncClient = request.app.state.client
    upstream_request = client.build_request(
        method=request.method,
        url=httpx.URL(path=path, query=request.url.query.encode()),
        headers=request.app.state.auth.upstream_headers(request.url.path, request.headers.items()),
        content=body,
    )
    request.state.upstream_t0 = time.perf_counter()
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        return _upstream_failure(request, exc)
    request.state.upstream_request_id = upstream.headers.get("x-request-id") or upstream.headers.get("request-id")
    return upstream


async def _read_capped(request: Request, upstream: httpx.Response) -> bytes | Response:
    """비스트리밍 상류 응답 본문을 상한(32MiB)까지 읽는다. 넘으면 502 — 메모리를 상한까지만 쓴다(D-110)."""
    chunks, size = [], 0
    try:
        async for chunk in upstream.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                request.state.upstream_error = "response_too_large"
                return error_format_for(request.url.path).error(
                    502, "upstream response too large", "upstream_error", "upstream_response_too_large")
            chunks.append(chunk)
    except httpx.RequestError as exc:        # 본문을 읽다 끊기거나 시간이 다 됐다
        return _upstream_failure(request, exc)
    finally:
        await upstream.aclose()
        request.state.upstream_ms = (time.perf_counter() - request.state.upstream_t0) * 1000
    return b"".join(chunks)


def _upstream_failure(request: Request, exc: httpx.RequestError) -> Response:
    """상류 호출 실패 → 그 API의 오류 형식. 풀 대기 초과는 503(상류에 보내지 않았다), 시간 초과는 504, 그 밖은 502."""
    fmt = error_format_for(request.url.path)
    request.state.upstream_error = type(exc).__name__   # 메시지는 남기지 않는다
    if isinstance(exc, httpx.PoolTimeout):
        return _busy(fmt.error(503, "upstream connection pool exhausted", "upstream_error", "upstream_busy"))
    if isinstance(exc, httpx.TimeoutException):   # 상류에서 실제로 시간을 썼다. 연결조차 못 했으면 None으로 둔다.
        request.state.upstream_ms = (time.perf_counter() - request.state.upstream_t0) * 1000
        return fmt.error(504, "upstream timed out", "upstream_error", "upstream_timeout")
    return fmt.error(502, "upstream unavailable", "upstream_error", "upstream_unavailable")


def _busy(response: Response) -> Response:
    response.headers["retry-after"] = "1"
    return response


def _pass_headers(upstream: httpx.Response, response: Response) -> None:
    """허용 목록의 상류 응답 헤더만 옮긴다(D-109). 같은 이름이 여럿이면 각각 보존한다(D-102)."""
    for name, value in upstream.headers.multi_items():
        if name.lower() in PASS_RESPONSE_HEADERS:
            response.headers.append(name, value)


def _downstream(upstream: httpx.Response, content: bytes) -> Response:
    response = Response(content=content, status_code=upstream.status_code)
    _pass_headers(upstream, response)
    return response


def _is_sse(upstream: httpx.Response) -> bool:
    return upstream.headers.get("content-type", "").lower().startswith("text/event-stream")


def _stream_response(request: Request, upstream: httpx.Response, chain: DetectorChain,
                     session: str, shape) -> StreamingResponse:
    """상류 SSE를 조각마다 흘려보낸다(D-106). 복원은 pii_mask 검사기의 볼트로, 감사 줄·볼트 해제는 스트림 끝에서.
    `shape`는 어댑터가 준 API별 스트림 모양이다(D-107 C)."""
    pii = next((d for d in chain.detectors if isinstance(d, PIIDetector) and d.mode == "mask"), None)
    if pii is not None and pii.vault.issued(session):
        restore = lambda text, escape=None: pii.vault.restore(session, text, escape)   # noqa: E731
        hold = lambda text: pii.vault.hold(session, text)                              # noqa: E731
    else:
        restore, hold = (lambda text, escape=None: (text, 0)), (lambda text: 0)       # 발급한 대체값이 없으면 손대지 않는다
    restorer = StreamRestorer(shape, restore, hold)
    response = StreamingResponse(iter(()), status_code=upstream.status_code)
    response.body_iterator = _pump(request, upstream, chain, session, restorer, pii, request.state.upstream_t0, response)
    _pass_headers(upstream, response)
    if pii is not None and pii.vault.issued(session):
        response.headers["x-gateway-pii"] = f"issued={pii.vault.issued(session)}"   # 머리가 본문보다 먼저 나간다 — 복원 수는 감사에만(D-113)
    return response


async def _pump(request: Request, upstream: httpx.Response, chain: DetectorChain, session: str,
                restorer: StreamRestorer, pii: PIIDetector | None, t0: float,
                response: Response) -> AsyncIterator[bytes]:
    """조각을 복원해 내보내고, 어떻게 끝나든(정상·상류 끊김·클라이언트 취소) 감사 줄을 정확히 한 줄 쓴다."""
    state = request.state
    size, error = 0, None
    try:
        async for data in upstream.aiter_bytes():
            if pii is not None:
                pii.vault.touch(session)     # ping·thinking만 오는 동안에도 매핑이 만료되지 않게(D-110)
            out = restorer.feed(data)
            if out:
                size += len(out)
                yield out
        out = restorer.finish()
        if out:
            size += len(out)
            yield out
    except BaseException as exc:
        error = type(exc).__name__      # 메시지는 남기지 않는다
        raise
    finally:
        state.upstream_ms = (time.perf_counter() - t0) * 1000   # 첫 바이트가 아니라 스트림 끝까지
        try:
            await upstream.aclose()
            state.response_steps = _stream_steps(session, restorer, pii)
            if session == state.request_id:
                await chain.release(session)
        finally:
            request.app.state.audit.write(_audit_record(
                request, response, (time.perf_counter() - state.t0) * 1000, error=error, res_bytes=size))


def _stream_steps(session: str, restorer: StreamRestorer, pii: PIIDetector | None) -> list[Step]:
    """스트림이 끝난 뒤의 응답 기록. 스트림에서 실제로 복원한 건수와 내보낸 출력 전체의 잔여 대체값 수 —
    감사는 사용자가 받은 것을 적는다(D-106). 응답 경로의 검사기는 pii_mask 하나다(D-109)."""
    if pii is None or not pii.vault.issued(session):
        return []
    return [Step("pii_mask", "restore", 0.0, "", {
        "restored": restorer.restored, "residual_tokens": pii.vault.residual(session, restorer.visible_text),
        "issued": pii.vault.issued(session), "suspect": pii.vault.suspect(session, restorer.visible_text)})]


def _as_text(content: bytes, content_type: str) -> str | None:
    """텍스트 응답만 후처리한다. 이미지·바이너리는 손대지 않는다."""
    ct = content_type.lower()
    if "json" not in ct and not ct.startswith("text/") and "xml" not in ct:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
