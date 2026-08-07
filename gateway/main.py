"""LLM Security Gateway — 패스스루 리버스 프록시 + 감사 로그.

4-A: 어떤 검사도 하지 않고 타겟에 그대로 중계한다.
     "게이트웨이를 껴도 타겟 앱 동작이 변하지 않는다"가 이 단계의 전부다.
4-B: 요청 1건마다 감사 로그 1줄. 지연을 세 갈래(종단/타겟/게이트웨이)로 분리 기록.
"""
from __future__ import annotations

import os
import time
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

from gateway.audit import AuditLog, digest, utcnow

load_dotenv()  # .env를 읽되, 이미 설정된 환경변수는 덮어쓰지 않는다

# 타겟 주소는 .env의 TARGET_URL 단일 출처를 그대로 쓴다(eval/ 스크립트와 동일 키).
# 기본값 8000은 D-002의 포트 계약(게이트웨이 8080 / 타겟 8000).
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8000").rstrip("/")
TARGET_TIMEOUT = float(os.environ.get("GATEWAY_TIMEOUT", "600"))  # D-023: 긴 생성 대비
AUDIT_LOG_PATH = os.environ.get("GATEWAY_LOG_PATH", "logs/gateway.jsonl")

# 게이트웨이 자체 경로. 감사 로그에서 제외한다.
# preflight.sh 같은 헬스체크가 초당 여러 번 때리면 지연 통계가 오염된다.
INTERNAL_PREFIX = "/__gateway/"

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
    state.blocked = False      # EVAL 3.3 자동 판정용. 4-C 이후 검사기가 채운다.

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
    })
    return response


def _int_or_none(v: str | None) -> int | None:
    return int(v) if v is not None and v.isdigit() else None


@app.get("/__gateway/health")
async def health() -> dict[str, str]:
    """게이트웨이 자체 상태. 언더스코어 2개로 타겟 앱 경로와 충돌을 피한다."""
    return {"status": "ok", "target": TARGET_URL}


@app.api_route("/{full_path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def passthrough(request: Request, full_path: str) -> Response:
    body = await request.body()
    request.state.req_bytes = len(body)
    request.state.req_digest = digest(body)

    t0 = time.perf_counter()
    upstream = await request.app.state.client.request(
        method=request.method,
        url=httpx.URL(path=f"/{full_path}", query=request.url.query.encode()),
        headers=_clean(request.headers, _DROP_REQ),
        content=body,
    )
    request.state.upstream_ms = (time.perf_counter() - t0) * 1000
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_clean(upstream.headers, _DROP_RES),
    )
