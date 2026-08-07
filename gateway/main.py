"""LLM Security Gateway — 4-A: 패스스루 리버스 프록시.

이 단계에서는 어떤 검사도 하지 않는다. 목표는 단 하나:
"게이트웨이를 껴도 타겟 앱 동작이 조금도 변하지 않는다"를 증명하는 것.
이 성질이 성립해야 EVAL 5.2의 증분 측정(방어 ON/OFF 비교)이 의미를 갖는다.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

load_dotenv()  # .env를 읽되, 이미 설정된 환경변수는 덮어쓰지 않는다

# 타겟 주소는 .env의 TARGET_URL 단일 출처를 그대로 쓴다(eval/ 스크립트와 동일 키).
# 기본값 8000은 D-002의 포트 계약(게이트웨이 8080 / 타겟 8000).
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8000").rstrip("/")
TARGET_TIMEOUT = float(os.environ.get("GATEWAY_TIMEOUT", "600"))  # D-023: 긴 생성 대비

# 홉 단위(hop-by-hop) 헤더 — "이 구간에서만 유효"한 라벨. 다음 구간으로 옮기면 안 된다.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
})

# 요청: host는 목적지가 바뀌었으니 httpx가 새로 붙이게, content-length는 재계산되게 뗀다.
_DROP_REQ = frozenset({"host", "content-length"})
# 응답: content-encoding은 httpx가 이미 압축을 풀어놨으므로 반드시 뗀다.
#       안 떼면 클라이언트가 "압축됐다"고 믿고 다시 풀려다 깨진다.
_DROP_RES = frozenset({"content-length", "content-encoding"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 수명 동안 클라이언트 1개만 두고 연결을 재사용한다.
    # 요청마다 새로 만들면 매번 TCP 핸드셰이크 → EVAL 4절 p95 목표를 혼자 다 까먹는다.
    app.state.client = httpx.AsyncClient(base_url=TARGET_URL, timeout=TARGET_TIMEOUT)
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(title="LLM Security Gateway", lifespan=lifespan)


def _clean(headers: Mapping[str, str], drop: frozenset[str]) -> dict[str, str]:
    return {k: v for k, v in headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() not in drop}


@app.get("/__gateway/health")
async def health() -> dict[str, str]:
    """게이트웨이 자체 상태. 언더스코어 2개로 타겟 앱 경로와 충돌을 피한다."""
    return {"status": "ok", "target": TARGET_URL}


@app.api_route("/{full_path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def passthrough(request: Request, full_path: str) -> Response:
    body = await request.body()
    upstream = await request.app.state.client.request(
        method=request.method,
        url=httpx.URL(path=f"/{full_path}", query=request.url.query.encode()),
        headers=_clean(request.headers, _DROP_REQ),
        content=body,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_clean(upstream.headers, _DROP_RES),
    )
