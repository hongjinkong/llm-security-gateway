"""LLM Security Gateway — 패스스루 리버스 프록시 + 감사 로그.

4-A: 어떤 검사도 하지 않고 타겟에 그대로 중계한다.
     "게이트웨이를 껴도 타겟 앱 동작이 변하지 않는다"가 이 단계의 전부다.
4-B: 요청 1건마다 감사 로그 1줄. 지연을 세 갈래(종단/타겟/게이트웨이)로 분리 기록.
4-C: 검사기 체인. 기본 구성은 검사기 0개이므로 동작은 4-A와 동일하다.
4-D: PII 탐지기(탐지만). GATEWAY_DETECTORS=pii
4-E: PII 마스킹 + 토큰 볼트.   GATEWAY_DETECTORS=pii_mask
4-F: 응답에 남은 마스킹 토큰을 원본으로 복원.
"""
from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from gateway.audit import AuditLog, digest, utcnow
from gateway.chain import ChainResult, DetectorChain
from gateway.detectors.base import Detector, Inspection
from gateway.detectors.noop import NoOpDetector
from gateway.detectors.pii import PIIDetector, session_of
from gateway.version import code_fingerprint

load_dotenv()  # .env를 읽되, 이미 설정된 환경변수는 덮어쓰지 않는다

# 타겟 주소는 .env의 TARGET_URL 단일 출처를 그대로 쓴다(eval/ 스크립트와 동일 키).
# 기본값 8000은 D-002의 포트 계약(게이트웨이 8080 / 타겟 8000).
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8000").rstrip("/")
TARGET_TIMEOUT = float(os.environ.get("GATEWAY_TIMEOUT", "600"))  # D-023: 긴 생성 대비
AUDIT_LOG_PATH = os.environ.get("GATEWAY_LOG_PATH", "logs/gateway.jsonl")

# 게이트웨이 자체 경로. 감사 로그에서 제외한다.
# preflight.sh 같은 헬스체크가 초당 여러 번 때리면 지연 통계가 오염된다.
INTERNAL_PREFIX = "/__gateway/"

# 차단 시 사용자에게 돌려줄 문구. 타겟(AnythingLLM)과 같은 스키마로 200을 반환한다.
# 403+오류 JSON을 주면 garak이 이를 '오류'로 처리해 total_evaluated에서 빠질 수 있고,
# 그러면 베이스라인(n=4000)과 방어 적용(n=?)을 비교하는 EVAL 5.2가 무효가 된다.
# 차단 여부는 HTTP 코드가 아니라 gateway_blocked 필드와 감사 로그로 판별한다.
BLOCKED_MESSAGE = os.environ.get(
    "GATEWAY_BLOCKED_MESSAGE", "요청이 보안 정책에 의해 차단되었습니다.")

# 활성 검사기 목록. 쉼표 구분. 기본값은 빈 문자열 = 검사기 없음 = 4-A와 동일 동작.
DETECTOR_NAMES = [x.strip() for x in os.environ.get("GATEWAY_DETECTORS", "").split(",") if x.strip()]

# 이름 → 생성자. 4-D부터 여기에 실제 검사기가 등록된다.
DETECTOR_REGISTRY: dict[str, Callable[[], Detector]] = {
    "noop": lambda: NoOpDetector("noop"),
    "pii": lambda: PIIDetector("detect"),
    "pii_mask": lambda: PIIDetector("mask"),
}


def build_chain(names: list[str] | None = None) -> DetectorChain:
    names = DETECTOR_NAMES if names is None else names
    unknown = [n for n in names if n not in DETECTOR_REGISTRY]
    if unknown:
        raise ValueError(f"알 수 없는 검사기: {unknown}. 등록된 것: {sorted(DETECTOR_REGISTRY)}")
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
    app.state.client = httpx.AsyncClient(base_url=TARGET_URL, timeout=TARGET_TIMEOUT)
    app.state.audit = AuditLog(AUDIT_LOG_PATH)
    app.state.chain = build_chain()
    try:
        yield
    finally:
        await app.state.client.aclose()
        app.state.audit.close()


app = FastAPI(title="LLM Security Gateway", lifespan=lifespan)


def _clean(headers: Mapping[str, str], drop: frozenset[str]) -> dict[str, str]:
    return {k: v for k, v in headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() not in drop}


# 요청: host는 목적지가 바뀌었으니 httpx가 새로 붙이게, content-length는 재계산되게 뗀다.
_DROP_REQ = frozenset({"host", "content-length"})
# 응답: content-encoding은 httpx가 이미 압축을 풀어놨으므로 반드시 뗀다(안 떼면 클라이언트가 깨짐).
_DROP_RES = frozenset({"content-length", "content-encoding"})


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

    t0 = time.perf_counter()
    response = await call_next(request)
    total_ms = (time.perf_counter() - t0) * 1000

    response.headers["X-Gateway-Request-Id"] = state.request_id

    if request.url.path.startswith(INTERNAL_PREFIX):
        return response

    upstream_ms = getattr(state, "upstream_ms", None)
    request.app.state.audit.write({
        "ts": utcnow(),
        "request_id": state.request_id,
        "method": request.method,
        "path": request.url.path,
        "query": request.url.query,
        "status": response.status_code,
        # EVAL 4절: 종단 지연 / 타겟 호출 / 게이트웨이 내부 처리를 분리한다.
        "total_ms": round(total_ms, 2),
        "upstream_ms": None if upstream_ms is None else round(upstream_ms, 2),
        "gateway_ms": round(total_ms - (upstream_ms or 0.0), 2),
        # 본문 원문은 남기지 않는다. 크기와 지문만.
        "req_bytes": getattr(state, "req_bytes", None),
        "req_sha256_12": getattr(state, "req_digest", None),
        "res_bytes": _int_or_none(response.headers.get("content-length")),
        "blocked": getattr(state, "blocked", False),
        "client": request.client.host if request.client else None,
        **_chain_fields(getattr(state, "chain_result", None)),
        "response_detectors": [s.as_dict() for s in getattr(state, "response_steps", [])],
    })
    return response


def _int_or_none(v: str | None) -> int | None:
    return int(v) if v is not None and v.isdigit() else None


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


@app.get("/__gateway/health")
async def health(request: Request) -> dict:
    """게이트웨이 자체 상태. 언더스코어 2개로 타겟 앱 경로와 충돌을 피한다.

    code와 detectors를 함께 보고한다. 측정 전에 이 둘만 확인하면
    "옛 이미지로 돌고 있음"과 "검사기 설정이 틀림"을 모두 걸러낼 수 있다.
    """
    return {
        "status": "ok",
        "target": TARGET_URL,
        "code": code_fingerprint(),
        "detectors": list(request.app.state.chain.names),
    }


@app.api_route("/{full_path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def passthrough(request: Request, full_path: str) -> Response:
    body = await request.body()
    request.state.req_bytes = len(body)
    request.state.req_digest = digest(body)

    chain = request.app.state.chain
    # 세션 식별은 요청의 속성이지 검사기의 사정이 아니다. 여기서 한 번 정해 공유한다.
    session = session_of(body, request.state.request_id)
    request.state.session = session

    result = await chain.run(Inspection(
        request_id=request.state.request_id,
        method=request.method,
        path=request.url.path,
        headers=request.headers,
        body=body,
        session=session,
    ))
    request.state.chain_result = result
    if result.blocked:
        request.state.blocked = True
        # 차단 시 타겟을 호출하지 않는다 → upstream_ms는 None으로 남는다.
        return JSONResponse(status_code=200, content={
            "id": request.state.request_id,
            "type": "textResponse",
            "textResponse": BLOCKED_MESSAGE,
            "sources": [],
            "error": None,
            "gateway_blocked": True,
            # 차단 사유는 응답에 넣지 않는다. 공격자에게 룰을 알려줄 이유가 없다.
            # 사유는 감사 로그에 있고 X-Gateway-Request-Id로 대조할 수 있다.
        })
    body = result.body   # TRANSFORM이 있었으면 바뀐 본문으로 중계한다

    t0 = time.perf_counter()
    upstream = await request.app.state.client.request(
        method=request.method,
        url=httpx.URL(path=f"/{full_path}", query=request.url.query.encode()),
        headers=_clean(request.headers, _DROP_REQ),
        content=body,
    )
    request.state.upstream_ms = (time.perf_counter() - t0) * 1000

    content = upstream.content
    text = _as_text(content, upstream.headers.get("content-type", ""))
    if text is not None:
        restored, steps = await chain.run_response(session, text)
        if steps:
            request.state.response_steps = steps
        if restored != text:
            content = restored.encode("utf-8")

    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=_clean(upstream.headers, _DROP_RES),
    )


def _as_text(content: bytes, content_type: str) -> str | None:
    """텍스트 응답만 후처리한다. 이미지·바이너리는 손대지 않는다."""
    ct = content_type.lower()
    if "json" not in ct and not ct.startswith("text/") and "xml" not in ct:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
