"""탐지 사이드카(D-125, PLAN 17단계) — 게이트웨이와 따로 도는 컨테이너. 게이트웨이 이미지는 onnxruntime·모델을 갖지 않는다.

  POST /v1/detect  {"texts": [{"id", "role", "text"}], "tasks": ["pii_ner"]}
                   → {"results": [{"id", "pii_ner": [{"start", "end", "label", "kind", "score"}]}], "ms"}
  GET  /health     → {"status": "ok", "tasks": {"pii_ner": {"model", "revision", "license", "sha256"}}}

원문은 저장하지도 기록하지도 않는다 — 접근 로그를 끄고(이미지 CMD), 오류 본문에 요청 내용을 싣지 않는다. 추론은 스레드에서 돌아 이벤트 루프가 /health를 계속 받는다.
한 요청의 비용에 상한이 있다: 본문 2MiB, 텍스트 1,024개, 글자 합 131,072·토큰 합 16,384(넘으면 추론 전에 413 too_many_tokens). 추론은 한 번에 하나다(ONNX가 이미 스레드 여럿을 쓴다 — 동시에 돌리면
서로 느려질 뿐이다) — 나머지는 줄을 선다. 짝 없는 서로게이트는 U+FFFD로 바꿔 본다(한 글자 대 한 글자라 위치가 그대로다).
환경변수: DETECT_MODEL(models.json의 이름), DETECT_MODEL_DIR(받은 모델 폴더), DETECT_THREADS(ONNX 스레드, 기본 4).
위치는 원문 문자(유니코드 코드 포인트) 기준이다 — 게이트웨이가 같은 문자열을 잘라 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from detect.ner import NER

TASKS = ("pii_ner",)
MAX_BODY = 2 * 1024 * 1024          # 게이트웨이 본문 상한(1MiB)의 텍스트가 JSON 이스케이프로 늘어도 들어오게
MAX_TEXTS = 1024
MAX_TOKENS = 16 * 1024              # 한 요청의 토큰 합 — 창 32개쯤(M2에서 veil 약 6초, atonlee 약 1초). 넘으면 추론하지 않는다
MAX_CHARS = MAX_TOKENS * 8          # 글자가 이보다 많으면 세지도 않는다 — 토큰 세기도 공짜가 아니다(70만 자에 3초)
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(ner: NER | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ner = ner or NER(os.environ.get("DETECT_MODEL", "veil-ko-lite-int8"), Path(os.environ.get("DETECT_MODEL_DIR", "models")),
                                   threads=int(os.environ.get("DETECT_THREADS", "4")))
        app.state.limiter = anyio.CapacityLimiter(1)
        yield

    app = FastAPI(title="detect sidecar", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    @app.get("/health")
    async def health(request: Request) -> dict:
        return {"status": "ok", "tasks": {"pii_ner": request.app.state.ner.info()}}

    @app.post("/v1/detect")
    async def detect(request: Request) -> Response:
        t0 = time.perf_counter()
        body, over = bytearray(), False
        try:
            async for chunk in request.stream():          # 상한을 넘어도 끝까지 읽는다 — 읽다 말고 답하면 Connection: close 클라이언트는 413 대신 연결 오류를 받는다
                over = over or len(body) + len(chunk) > MAX_BODY
                if not over:
                    body += chunk
        except ClientDisconnect:
            return Response(status_code=400)              # 받을 쪽이 없다
        if over:
            return _error(413, "request_too_large", f"body exceeds {MAX_BODY} bytes")
        try:
            req = json.loads(body)
        except (ValueError, RecursionError):              # 깊게 중첩된 배열은 RecursionError다
            return _error(400, "invalid_json", "body is not JSON")
        texts = req.get("texts") if isinstance(req, dict) else None
        tasks = req.get("tasks", list(TASKS)) if isinstance(req, dict) else None
        if not isinstance(texts, list) or not 0 < len(texts) <= MAX_TEXTS or not all(
                isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("text"), str)
                and not LONE_SURROGATE.search(t["id"]) for t in texts):
            return _error(400, "invalid_texts", f"texts must be 1..{MAX_TEXTS} objects with string id and text")
        if not isinstance(tasks, list) or not tasks or any(t not in TASKS for t in tasks):
            return _error(400, "invalid_tasks", f"tasks must be a non-empty subset of {list(TASKS)}")
        ner: NER = request.app.state.ner
        clean = [LONE_SURROGATE.sub("\ufffd", t["text"]) for t in texts]

        def work() -> list[list[dict]] | None:
            if sum(map(len, clean)) > MAX_CHARS:                          # 세지도 않는다
                return None
            encs = [ner.encode(t) for t in clean]                         # 한 번 잘라 세고, 그대로 추론에 쓴다
            if sum(len(e.ids) for e in encs) > MAX_TOKENS:
                return None
            return [ner.predict(t, e) for t, e in zip(clean, encs)]

        found = await anyio.to_thread.run_sync(work, limiter=request.app.state.limiter)
        if found is None:
            return _error(413, "too_many_tokens", f"texts exceed {MAX_TOKENS} tokens in total")
        return JSONResponse({"results": [{"id": t["id"], "pii_ner": spans} for t, spans in zip(texts, found)],
                             "ms": round((time.perf_counter() - t0) * 1000, 2)})

    return app


app = create_app()
