"""LLM Security Gateway — 패스스루 리버스 프록시 + 감사 로그.

4-A: 어떤 검사도 하지 않고 타겟에 그대로 중계한다.
     "게이트웨이를 껴도 타겟 앱 동작이 변하지 않는다"가 이 단계의 전부다.
4-B: 요청 1건마다 감사 로그 1줄. 지연을 세 갈래(종단/타겟/게이트웨이)로 분리 기록.
4-C: 검사기 체인. 기본 구성은 검사기 0개이므로 동작은 4-A와 동일하다.
4-D: PII 탐지기(탐지만). GATEWAY_DETECTORS=pii
4-E: PII 마스킹 + 토큰 볼트.   GATEWAY_DETECTORS=pii_mask
5-A: 룰 기반 인젝션 탐지.     GATEWAY_DETECTORS=injection_rule,pii_mask (순서는 D-037)
     이력은 가리고 이번 턴만으로 막는 판: GATEWAY_DETECTORS=injection_rule_turn,pii_mask (D-095·D-099)
5-B·5-C: 2차 유사도·3차 LLM Judge는 사전 기준으로 기각됐다(D-052·D-054).
     코드는 `v1` 태그에만 있다(D-099). 쓰지 않는 방어 코드를 배포물에 두지 않는다.
4-F: 응답에 남은 마스킹 토큰을 원본으로 복원.
6-A: 카나리 관측. **응답을 바꾸지 않는다**(D-058 / docs/CANARY_DESIGN.md).
     GATEWAY_DETECTORS=injection_rule,pii_mask,canary_observe
     목록 맨 뒤 = 응답 경로 맨 앞 = 타겟 원본을 본다. 맨 뒤가 아니면 기동 실패한다.
     값 3개(GATEWAY_CANARY_A/_B/_DOC)가 없어도 기동 실패한다 — 값 없이 관측하면
     검출률이 조용히 0이 되고 그 0이 D-059의 입력이 된다.
D-099: 본문 크기 상한(GATEWAY_MAX_BODY_BYTES, 기본 1MiB)을 넘으면 413.
     sessionId 없는 요청의 볼트 매핑은 응답 뒤 바로 버린다(TTL까지 원문을 들고 있지 않는다).
D-106: `stream: true`는 상류 SSE를 조각마다 흘려보낸다(gateway/streaming.py가 토큰을 복원한다).
     감사 줄은 스트림이 끝난 뒤 한 줄, 차단은 SSE 한 조각 + [DONE]. 옛 경로(/v1 밖)는 그대로다.
D-107 A: 클라이언트 인증(GATEWAY_CLIENT_KEYS, 없으면 기동 실패 — GATEWAY_AUTH=off로만 연다)과 상류 키 보관
     (GATEWAY_UPSTREAM_KEY — 클라이언트의 인증 헤더를 떼고 상류 형식으로 단다). 볼트는 요청 단위다 —
     클라이언트가 보낸 sessionId는 더 이상 볼트 키가 아니고, 응답(스트림)이 끝나면 버린다.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import replace
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from gateway.api import ApiError, Doc, adapter_for, error_format_for
from gateway.audit import AuditLog, digest, utcnow
from gateway.auth import Auth, parse_client_keys
from gateway.chain import ChainResult, DetectorChain, Step
from gateway.detectors.base import Detector, Inspection
from gateway.detectors.canary import CanaryObserveDetector, validate_canary_position
from gateway.detectors.injection import InjectionRuleDetector
from gateway.detectors.noop import NoOpDetector
from gateway.detectors.pii import ALL_KINDS, PIIDetector
from gateway.metrics import Metrics
from gateway.ratelimit import RateLimiter
from gateway.streaming import StreamRestorer
from gateway.version import canary_fingerprint, code_fingerprint

load_dotenv()  # .env를 읽되, 이미 설정된 환경변수는 덮어쓰지 않는다

# 타겟 주소는 .env의 TARGET_URL 단일 출처를 그대로 쓴다(eval/ 스크립트와 동일 키).
# 기본값 8000은 D-002의 포트 계약(게이트웨이 8080 / 타겟 8000).
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

# 게이트웨이 자체 경로. 감사 로그에서 제외한다.
# preflight.sh 같은 헬스체크가 초당 여러 번 때리면 지연 통계가 오염된다.
INTERNAL_PREFIX = "/__gateway/"

# 차단 시 사용자에게 돌려줄 문구. 타겟(AnythingLLM)과 같은 스키마로 200을 반환한다.
# 403+오류 JSON을 주면 garak이 이를 '오류'로 처리해 total_evaluated에서 빠질 수 있고,
# 그러면 베이스라인(n=4000)과 방어 적용(n=?)을 비교하는 EVAL 5.2가 무효가 된다.
# 차단 여부는 HTTP 코드가 아니라 gateway_blocked 필드와 감사 로그로 판별한다.
BLOCKED_MESSAGE = os.environ.get(
    "GATEWAY_BLOCKED_MESSAGE", "요청이 보안 정책에 의해 차단되었습니다.")

# D-099: 본문 크기 상한. 상한이 없으면 큰 요청 하나가 메모리와 검사기 시간을 독차지하고,
# 워커가 1개라 그동안 다른 요청이 전부 멈춘다. 이미지 첨부처럼 큰 요청을 받으려면 값을 올린다
# (OpenAI 경로의 검사기는 text 파트만 보므로 이미지 크기는 검사 시간에 들어가지 않는다).
MAX_BODY_BYTES = int(os.environ.get("GATEWAY_MAX_BODY_BYTES", str(1024 * 1024)))

# D-107 A: 인증. 키 목록이 없으면 lifespan에서 기동을 실패시킨다 — 보안 제품은 닫힌 채로 시작한다.
# 무인증은 GATEWAY_AUTH=off로 명시한 로컬 실험에서만. 상류 키가 있으면 클라이언트의 인증 헤더를 떼고 상류 형식으로 단다.
AUTH_OFF = os.environ.get("GATEWAY_AUTH", "").strip().lower() == "off"
CLIENT_KEYS_SPEC = os.environ.get("GATEWAY_CLIENT_KEYS", "")
AUTH = Auth(None if AUTH_OFF else parse_client_keys(CLIENT_KEYS_SPEC) or None,
            os.environ.get("GATEWAY_UPSTREAM_KEY", ""))

# 6단계 카나리 관측(D-058 / CANARY_DESIGN 3-2). 값의 단일 출처는 .env이고 compose가
# 세 줄로 넘긴다(R1). **값을 읽는 곳은 여기 하나뿐이고 검사기는 환경변수를 모른다** —
# 출처가 한 군데여야 health의 지문과 대조가 성립한다(R5).
#
# 기본값을 두지 않는다. 값이 없으면 빈 문자열이 되고 prepare()가 기동을 실패시킨다(R3).
# "적당한 기본값"을 주면 검출률이 조용히 0인 채로 측정이 돌고, 그 0이 D-059의 입력이 된다.
CANARY_A = os.environ.get("GATEWAY_CANARY_A", "")
CANARY_B = os.environ.get("GATEWAY_CANARY_B", "")
CANARY_DOC = os.environ.get("GATEWAY_CANARY_DOC", "")

# D-107 D: 제품 설정 세 개 — GATEWAY_INJECTION(observe 기본|block|off), GATEWAY_INJECTION_SCOPE(turn 기본|all), GATEWAY_PII(mask 기본|detect|off).
# 카나리는 값 셋이 다 있으면 켜진다. 체인 순서는 고정이다: injection → pii → canary.
# 저수준 목록 GATEWAY_DETECTORS(쉼표 구분)는 측정·테스트용으로 남긴다 — **설정돼 있으면 그것이 우선**이고, 빈 문자열은 검사기 없음(4-A)이다.
PII_KINDS = tuple(x.strip() for x in os.environ.get("GATEWAY_PII_KINDS", ",".join(ALL_KINDS)).split(",") if x.strip())


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
    if CANARY_A and CANARY_B and CANARY_DOC:
        names.append("canary_observe")
    return names


# 이름 → 생성자. 4-D부터 여기에 실제 검사기가 등록된다.
DETECTOR_REGISTRY: dict[str, Callable[[], Detector]] = {
    "noop": lambda: NoOpDetector("noop"),
    "pii": lambda: PIIDetector("detect", kinds=PII_KINDS),
    "pii_mask": lambda: PIIDetector("mask", kinds=PII_KINDS),
    "injection_observe": lambda: InjectionRuleDetector(mode="observe"),
    "injection_rule": lambda: InjectionRuleDetector(),
    "injection_rule_turn": lambda: InjectionRuleDetector(scope="turn"),
    "canary_observe": lambda: CanaryObserveDetector(CANARY_A, CANARY_B, CANARY_DOC),
}


def build_chain(names: list[str] | None = None) -> DetectorChain:
    names = detector_names_from_env() if names is None else names
    unknown = [n for n in names if n not in DETECTOR_REGISTRY]
    if unknown:
        raise ValueError(f"알 수 없는 검사기: {unknown}. 등록된 것: {sorted(DETECTOR_REGISTRY)}")
    # 카나리 관측은 목록 맨 뒤 = 응답 경로 맨 앞이어야 타겟 원본을 본다(D-058 / 설계 4-1).
    # lifespan에서 불리므로 여기서 던지면 **게이트웨이가 기동하지 못한다**(D-048 패턴).
    validate_canary_position(names)
    return DetectorChain([DETECTOR_REGISTRY[n]() for n in names])

# 홉 단위(hop-by-hop) 헤더 — "이 구간에서만 유효"한 라벨. 다음 구간으로 옮기면 안 된다.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 수명 동안 클라이언트 1개만 두고 연결을 재사용한다.
    # 요청마다 새로 만들면 매번 TCP 핸드셰이크 → EVAL 4절 p95 목표를 혼자 다 까먹는다.
    if not CHAT_UPSTREAM_PATH.startswith("/"):
        raise RuntimeError(f"GATEWAY_CHAT_UPSTREAM_PATH는 /로 시작하는 경로여야 한다: {CHAT_UPSTREAM_PATH!r}")
    if not AUTH.enabled and not AUTH_OFF:
        raise RuntimeError("GATEWAY_CLIENT_KEYS가 없다 — 클라이언트 키 없이는 기동하지 않는다(D-107 A). "
                           "`python -m gateway keygen`으로 키를 만들어 넣거나, 로컬 실험이면 GATEWAY_AUTH=off를 명시한다")
    app.state.auth = AUTH
    app.state.client = httpx.AsyncClient(base_url=TARGET_URL, timeout=TARGET_TIMEOUT)
    app.state.metrics = Metrics()
    app.state.audit = AuditLog(AUDIT_LOG_PATH, AUDIT_LOG_MAX_BYTES, AUDIT_LOG_BACKUPS, on_write=app.state.metrics.observe)
    app.state.ratelimit = RateLimiter(RATE_PER_MINUTE)
    app.state.chain = build_chain()
    # 코퍼스 임베딩 같은 무거운 준비는 여기서 끝낸다(D-043). 실패하면 기동을 실패시킨다 —
    # 준비 안 된 검사기를 달고 뜨면 방어가 꺼진 채로 측정이 돌아간다.
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


def _clean(pairs: Iterable[tuple[str, str]], drop: frozenset[str]) -> list[tuple[str, str]]:
    """(이름, 값) 쌍 목록을 그대로 거른다. dict로 모으면 같은 이름의 헤더(Set-Cookie 둘, X-Forwarded-For 둘)가
    하나로 합쳐지거나 마지막 것만 남는다(D-102)."""
    return [(k, v) for k, v in pairs
            if k.lower() not in HOP_BY_HOP and k.lower() not in drop]


# 요청: host는 목적지가 바뀌었으니 httpx가 새로 붙이게, content-length는 재계산되게 뗀다.
# accept-encoding도 뗀다 — 클라이언트가 br·zstd를 받겠다고 했는데 게이트웨이의 httpx가 그걸 못 풀면,
# 압축된 바이트가 content-encoding 없이 그대로 나가고 토큰도 복원되지 않는다. httpx가 자기가 풀 수 있는 것만 알린다(D-102).
_DROP_REQ = frozenset({"host", "content-length", "accept-encoding"})
# 응답: content-encoding은 httpx가 이미 압축을 풀어놨으므로 반드시 뗀다(안 떼면 클라이언트가 깨짐).
# date·server는 게이트웨이의 서버가 새로 붙인다 — 상류 것까지 넘기면 둘씩 찍힌다(D-102).
_DROP_RES = frozenset({"content-length", "content-encoding", "date", "server"})


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
    state.streaming = False      # 스트리밍 응답이면 감사 줄은 응답 생성기가 스트림 끝에서 쓴다(D-106)
    state.client = None          # 인증된 클라이언트 키의 이름(D-107 A). 무인증·실패면 None
    state.api = None             # 어댑터 이름(D-107 C). 옛 경로면 None

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
        "api": getattr(state, "api", None),                # chat | messages | responses | null(옛 경로) (D-107 C)
        **_chain_fields(getattr(state, "chain_result", None)),
        "response_detectors": [s.as_dict() for s in getattr(state, "response_steps", [])],
    }


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


@app.get("/__gateway/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus 텍스트 형식(D-107 E). 감사 레코드에서 센 값이라 감사 줄과 어긋나지 않는다. 인증 불필요(내부 경로)."""
    return Response(request.app.state.metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/__gateway/health")
async def health(request: Request) -> dict:
    """게이트웨이 자체 상태. 언더스코어 2개로 타겟 앱 경로와 충돌을 피한다.

    code와 detectors를 함께 보고한다. 측정 전에 이 둘만 확인하면
    "옛 이미지로 돌고 있음"과 "검사기 설정이 틀림"을 모두 걸러낼 수 있다.

    `canary_fp`는 게이트웨이가 **읽은 값의 지문**이다. 값이 아니다(R4).
    `.env`의 지문 · 마지막 `setup_target.py`의 지문과 셋이 같아야 관측이
    성립한다 — `scripts/verify_gateway.sh`가 대조한다(R5 / 설계 3-2).
    값이 비어 있으면 null이다.
    """
    return {
        "status": "ok",
        "target": TARGET_URL,
        "chat_upstream_path": CHAT_UPSTREAM_PATH,
        "code": code_fingerprint(),
        "detectors": list(request.app.state.chain.names),
        "canary_fp": {
            "canary_a": canary_fingerprint(CANARY_A) if CANARY_A else None,
            "canary_b": canary_fingerprint(CANARY_B) if CANARY_B else None,
            "canary_doc": canary_fingerprint(CANARY_DOC) if CANARY_DOC else None,
        },
    }


@app.api_route("/{full_path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def passthrough(request: Request, full_path: str) -> Response:
    # 인증을 본문보다 먼저 본다(D-107 A) — 틀린 키의 본문은 읽지도, 검사하지도, 중계하지도 않는다.
    auth: Auth = request.app.state.auth
    request.state.client = auth.client_of(request.headers)
    if auth.enabled and request.state.client is None:
        request.state.upstream_error = "unauthorized"
        return error_format_for(request.url.path).error(401, "invalid or missing API key", "authentication_error", "invalid_api_key")
    # 레이트리밋(D-107 E): 클라이언트 이름(무인증이면 IP)마다 분당 상한. 본문을 읽기 전에 거른다.
    ok, retry_after = request.app.state.ratelimit.allow(
        request.state.client or (request.client.host if request.client else "?"))
    if not ok:
        request.state.upstream_error = "rate_limited"
        response = error_format_for(request.url.path).error(429, "rate limit exceeded", "rate_limit_error", "rate_limit_exceeded")
        response.headers["retry-after"] = str(retry_after)
        return response
    body, size = await _read_body(request)
    request.state.req_bytes = size
    if body is None:
        # 상류도 검사기도 부르지 않는다. 감사 줄은 미들웨어가 413으로 남긴다.
        return error_format_for(request.url.path).error(
            413, f"request body exceeds {MAX_BODY_BYTES} bytes", "invalid_request_error", "request_too_large")
    request.state.req_digest = digest(body)

    # D-107 C: 아는 API(Chat Completions·Messages·Responses)의 POST는 어댑터가 한 번 파싱한다. 검사기는 그 doc를 본다.
    # OPTIONS(CORS 프리플라이트)·HEAD에는 본문이 없다(D-102). 그 밖의 경로는 옛 경로 — 바이트 검사(v1 측정 입구).
    doc = None
    adapter = adapter_for(request.url.path) if request.method == "POST" else None
    if adapter is not None:
        try:
            doc = Doc(adapter, adapter.parse(body))
        except ApiError as exc:
            return adapter.error(exc.status, str(exc), exc.type_, exc.code, exc.param)
    request.state.api = adapter.name if adapter else None

    chain = request.app.state.chain
    # 볼트는 요청 단위다(D-107 A). 클라이언트가 보낸 sessionId는 키가 아니다 — 그것을 맞추면 남의 원문을
    # 꺼낼 수 있었다(D-107 §1 #1). 다음 턴 이력의 원문은 다시 가려지므로(D-099) 대화 간 상태가 필요 없다.
    session = request.state.session = request.state.request_id
    try:
        return await _relay(request, full_path, body, doc, chain, session)
    finally:
        # 응답이 나가면 매핑을 다시 쓸 일이 없다 — 차단·상류 오류·예외로 끝나도 바로 버린다.
        # 스트리밍 응답은 스트림이 끝난 뒤 생성기가 해제한다(D-106): 여기서 먼저 버리면 조각을 복원할 원문이 없다.
        if not request.state.streaming:
            await chain.release(session)


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


async def _relay(request: Request, full_path: str, body: bytes, doc: Doc | None,
                 chain: DetectorChain, session: str) -> Response:
    """검사기 체인 → (차단 또는) 상류 호출 → 응답 후처리."""
    result = await chain.run(Inspection(
        request_id=request.state.request_id,
        method=request.method,
        path=request.url.path,
        headers=request.headers,
        body=body,
        session=session,
        doc=doc,
    ))
    request.state.chain_result = result
    adapter = doc.adapter if doc is not None else None
    wants_stream = doc is not None and adapter.wants_stream(doc.payload)
    if result.blocked:
        request.state.blocked = True
        # 차단 시 타겟을 호출하지 않는다 → upstream_ms는 None으로 남는다.
        # 차단 사유는 응답에 넣지 않는다(D-040). 요청 ID만 넣는다 — 사용자가 운영자에게 물을 수 있는 손잡이다(D-107 E).
        message = f"{BLOCKED_MESSAGE} (요청 ID: {request.state.request_id})"
        if adapter is not None:
            return adapter.blocked(doc.payload, request.state.request_id, message, wants_stream)
        return JSONResponse(status_code=200, content={
            "id": request.state.request_id,
            "type": "textResponse",
            "textResponse": message,
            "sources": [],
            "error": None,
            "gateway_blocked": True,
        })
    body = result.body   # TRANSFORM이 있었으면 바뀐 본문으로 중계한다

    t0 = time.perf_counter()
    client: httpx.AsyncClient = request.app.state.client
    upstream_request = client.build_request(
        method=request.method,
        url=httpx.URL(path=adapter.upstream_path() if adapter is not None else f"/{full_path}",
                      query=request.url.query.encode()),
        headers=request.app.state.auth.upstream_headers(request.url.path, _clean(request.headers.items(), _DROP_REQ)),
        content=body,
    )
    try:
        # stream: true면 머리만 받고 본문은 이터레이터로 연다. SSE가 아니면(상류 오류 JSON, 스트리밍을 무시하는 상류)
        # 통째로 읽어 아래 비스트리밍 후처리로 간다 — D-086의 오류 중계 계약이 그대로다(D-106).
        upstream = await client.send(upstream_request, stream=wants_stream)
        if wants_stream and not _is_sse(upstream):
            await upstream.aread()
    except httpx.RequestError as exc:
        # D-086: API 입구는 상류 장애를 그 API의 오류 형식 502/504로 돌려준다. 옛 경로는 예전대로
        # 예외를 올려 500(감사 줄은 미들웨어가 남긴다) — v1 측정 경로의 계약을 바꾸지 않는다.
        if adapter is None:
            raise
        timed_out = isinstance(exc, httpx.TimeoutException)
        if timed_out:   # 상류에서 실제로 시간을 썼다. 연결조차 못 했으면 None으로 둔다.
            request.state.upstream_ms = (time.perf_counter() - t0) * 1000
        request.state.upstream_error = type(exc).__name__   # 메시지는 남기지 않는다
        return adapter.error(504 if timed_out else 502,
                             "upstream timed out" if timed_out else "upstream unavailable",
                             "upstream_error", "upstream_timeout" if timed_out else "upstream_unavailable")
    if wants_stream and _is_sse(upstream):
        request.state.streaming = True
        return _stream_response(request, upstream, chain, session, adapter.stream_shape(), t0)
    request.state.upstream_ms = (time.perf_counter() - t0) * 1000

    content = upstream.content
    text = _as_text(content, upstream.headers.get("content-type", ""))
    if text is not None:
        restored, steps = await chain.run_response(session, text)
        if steps:
            request.state.response_steps = steps
        if restored != text:
            content = restored.encode("utf-8")

    response = Response(content=content, status_code=upstream.status_code)
    for name, value in _clean(upstream.headers.multi_items(), _DROP_RES):
        response.headers.append(name, value)   # 같은 이름의 헤더를 각각 보존한다
    return response


def _is_sse(upstream: httpx.Response) -> bool:
    return upstream.headers.get("content-type", "").lower().startswith("text/event-stream")


def _stream_response(request: Request, upstream: httpx.Response, chain: DetectorChain,
                     session: str, shape, t0: float) -> StreamingResponse:
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
    response.body_iterator = _pump(request, upstream, chain, session, restorer, pii, t0, response)
    for name, value in _clean(upstream.headers.multi_items(), _DROP_RES):
        response.headers.append(name, value)
    return response


async def _pump(request: Request, upstream: httpx.Response, chain: DetectorChain, session: str,
                restorer: StreamRestorer, pii: PIIDetector | None, t0: float,
                response: Response) -> AsyncIterator[bytes]:
    """조각을 복원해 내보내고, 어떻게 끝나든(정상·상류 끊김·클라이언트 취소) 감사 줄을 정확히 한 줄 쓴다."""
    state = request.state
    size, error = 0, None
    try:
        async for data in upstream.aiter_bytes():
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
            state.response_steps = await _stream_steps(chain, session, restorer, pii)
            if session == state.request_id:
                await chain.release(session)
        finally:
            request.app.state.audit.write(_audit_record(
                request, response, (time.perf_counter() - state.t0) * 1000, error=error, res_bytes=size))


async def _stream_steps(chain: DetectorChain, session: str, restorer: StreamRestorer,
                        pii: PIIDetector | None) -> list[Step]:
    """스트림이 끝난 뒤의 응답 검사기 기록. 이어 붙인 원문 content 전체에 체인을 돌리고(카나리는 조각에 걸친 값도
    한 번으로 센다), pii_mask 항목은 스트림에서 실제로 복원한 건수와 내보낸 출력 전체의 잔여 토큰 수로 바꾼다 —
    감사는 사용자가 받은 것을 적는다(D-106)."""
    _, steps = await chain.run_response(session, restorer.content_in)
    if pii is None or not pii.vault.issued(session):
        return steps
    meta = {"restored": restorer.restored, "residual_tokens": pii.vault.residual(session, restorer.out_text),
            "issued": pii.vault.issued(session)}
    if any(s.detector == "pii_mask" for s in steps):
        return [replace(s, meta=meta) if s.detector == "pii_mask" else s for s in steps]
    if any(meta.values()):
        steps.append(Step("pii_mask", "restore", 0.0, "", meta))
    return steps


def _as_text(content: bytes, content_type: str) -> str | None:
    """텍스트 응답만 후처리한다. 이미지·바이너리는 손대지 않는다."""
    ct = content_type.lower()
    if "json" not in ct and not ct.startswith("text/") and "xml" not in ct:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
