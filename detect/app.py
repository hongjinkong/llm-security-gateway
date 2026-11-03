"""탐지 사이드카(D-125·D-127) — 게이트웨이와 따로 도는 컨테이너. 게이트웨이 이미지는 onnxruntime·모델을 갖지 않는다.

  POST /v1/detect  {"texts": [{"id", "role", "text"}], "tasks": ["pii_ner", "injection"]}
                   → {"results": [{"id", "pii_ner": [{"start", "end", "label", "kind", "score"}], "injection": 점수}], "ms"}
  POST /v1/guard   {"texts": [{"role", "text"}]} → {"verdict": "allow"|"block", "score"}   (게이트웨이 가드레일 웹훅 계약, D-127)
  GET  /health     → {"status": "ok", "tasks": {"pii_ner": {"model", "revision", "license", "sha256"}, "injection": {…, "threshold"}}}

원문은 저장하지도 기록하지도 않는다 — 접근 로그를 끄고(이미지 CMD), 오류 본문에 요청 내용을 싣지 않는다. 추론은 스레드에서 돌아 이벤트 루프가 /health를 계속 받는다.
한 요청의 비용에 상한이 있다: 본문 2MiB, 텍스트 1,024개, NER은 글자 합 131,072·토큰 합 16,384(넘으면 추론 없이 413 too_many_tokens).
인젝션은 캐시에 없는 텍스트만 새 글(뒤)부터 재되 비용 합이 DETECT_INJECTION_MAX_TOKENS(기본 2,048 — 채택 모델은 창 하나(512토큰)가 M2에서 약 0.6초라 게이트웨이 기한 5초 안)를
넘지 않을 만큼만 잰다. 비용은 창마다 (창 길이 + 특수 토큰 + 고정 비용 16) — 짧은 글 1,024개도 창 1,024개의 시간이 든다(D-127 재검증). 잰 것은 캐시하므로 다음 단계에서는 남은 글을 잰다.
/v1/guard는 못 잰 텍스트 수를 `unscored`로 알린다(게이트웨이는 block이면 막는다), /v1/detect는 하나라도 못 재면 413.
추론은 작업마다 한 번에 하나다(ONNX가 이미 스레드 여럿을 쓴다) — NER과 분류기는 줄을 따로 선다(가드레일 관측이 이름·주소 가림을 503으로 밀어내지 않게, D-127 리뷰).
차례가 왔을 때 클라이언트가 이미 끊었으면(게이트웨이가 기한을 넘겨 포기했으면) 돌리지 않는다.
짝 없는 서로게이트는 U+FFFD로 바꿔 본다(한 글자 대 한 글자라 위치가 그대로다).
인젝션 점수는 텍스트 SHA-256 → 점수 캐시(4,096, 원문 없음)에 둔다 — 에이전트 루프는 이번 턴의 도구 결과를 단계마다 다시 보낸다.
환경변수: DETECT_MODEL(NER — models.json의 이름, 비면 이 작업 없음), DETECT_INJECTION_MODEL(분류기, 비면 없음 — 이미지 기본), DETECT_GUARD_THRESHOLD(/v1/guard의 문턱,
0 초과 1 이하 — 없으면 그 모델의 threshold), DETECT_INJECTION_MAX_TOKENS(위 상한), DETECT_MODEL_DIR(받은 모델 폴더), DETECT_THREADS(ONNX 스레드, 기본 4).
위치는 원문 문자(유니코드 코드 포인트) 기준이다 — 게이트웨이가 같은 문자열을 잘라 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import OrderedDict
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from tokenizers import Encoding

from detect.classify import Classifier
from detect.decode import windows
from detect.ner import NER

MAX_BODY = 2 * 1024 * 1024          # 게이트웨이 본문 상한(1MiB)의 텍스트가 JSON 이스케이프로 늘어도 들어오게
MAX_TEXTS = 1024
MAX_TOKENS = 16 * 1024              # 한 요청의 토큰 합 — 창 32개쯤(M2에서 veil 약 6초, atonlee 약 1초). 넘으면 추론하지 않는다
MAX_CHARS = MAX_TOKENS * 8          # 글자가 이보다 많으면 세지도 않는다 — 토큰 세기도 공짜가 아니다(70만 자에 3초)
CACHE = 4096                        # 인젝션 점수 캐시(텍스트 SHA-256 → 점수)
INJECTION_MAX_TOKENS = 2048         # 인젝션 한 요청의 비용 상한 기본값(DETECT_INJECTION_MAX_TOKENS) — 꽉 찬 창 약 4개
WINDOW_OVERHEAD = 16                # 창 하나를 돌리는 고정 비용(토큰 환산, M2 측정 — 짧은 창도 수 ms가 든다)
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _number(var: str, default: float | None, upper: float) -> float:
    """0 초과 upper 이하의 유한한 수 — 아니면 기동하지 않는다(nan 문턱이면 모든 판정이 allow가 된다). 기본값이 없으면(문턱 없는 모델) 꼭 줘야 한다."""
    raw = os.environ.get(var, "").strip()
    if not raw and default is None:
        raise RuntimeError(f"{var}가 필요하다 — 이 모델은 models.json에 운영 문턱이 없다(D-127 — 0.5로 조용히 쓰지 않는다)")
    try:
        value = float(raw or default or "nan")
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and 0 < value <= upper):
        raise RuntimeError(f"{var}는 0 초과 {upper:g} 이하여야 한다: {raw!r}")
    return value


def create_app(ner: NER | None = None, clf: Classifier | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        root, threads = Path(os.environ.get("DETECT_MODEL_DIR", "models")), int(os.environ.get("DETECT_THREADS", "4"))
        if ner is None and clf is None:            # 테스트·bench가 모델을 넘기면 환경변수를 읽지 않는다
            ner_name, clf_name = os.environ.get("DETECT_MODEL", "veil-ko-lite-int8"), os.environ.get("DETECT_INJECTION_MODEL", "")
            models = {"pii_ner": NER(ner_name, root, threads=threads) if ner_name else None,
                      "injection": Classifier(clf_name, root, threads=threads) if clf_name else None}
        else:
            models = {"pii_ner": ner, "injection": clf}
        app.state.models = {task: m for task, m in models.items() if m is not None}
        if not app.state.models:
            raise RuntimeError("DETECT_MODEL·DETECT_INJECTION_MODEL이 둘 다 비었다 — 할 작업이 없다")
        if "injection" in app.state.models:
            app.state.threshold = _number("DETECT_GUARD_THRESHOLD", app.state.models["injection"].threshold, 1.0)
            app.state.inj_tokens = int(_number("DETECT_INJECTION_MAX_TOKENS", INJECTION_MAX_TOKENS, MAX_TOKENS))
            if app.state.inj_tokens < 1:
                raise RuntimeError("DETECT_INJECTION_MAX_TOKENS는 1 이상이어야 한다")
        app.state.limiters = {task: anyio.CapacityLimiter(1) for task in app.state.models}     # 작업마다 한 번에 하나
        app.state.cache = OrderedDict()
        yield

    app = FastAPI(title="detect sidecar", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    @app.get("/health")
    async def health(request: Request) -> dict:
        info = {task: m.info() for task, m in request.app.state.models.items()}
        if "injection" in info:
            info["injection"]["threshold"] = request.app.state.threshold
        return {"status": "ok", "tasks": info}

    async def read(request: Request, need_id: bool) -> list[dict] | Response:
        """본문 → 검사한 texts. 틀리면 그 오류 응답(요청 내용을 싣지 않는다)."""
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
        if not isinstance(texts, list) or not 0 < len(texts) <= MAX_TEXTS or not all(
                isinstance(t, dict) and isinstance(t.get("text"), str)
                and (not need_id or isinstance(t.get("id"), str) and not LONE_SURROGATE.search(t["id"])) for t in texts):
            return _error(400, "invalid_texts", f"texts must be 1..{MAX_TEXTS} objects with string {'id and ' if need_id else ''}text")
        request.state.req = req
        return texts

    async def run(request: Request, tasks: list[str], raw: list[str], partial: bool = False) -> list[dict] | None | Response:
        """텍스트마다 {작업: 결과}. 상한을 넘으면 None(추론하지 않는다), 차례가 왔을 때 클라이언트가 끊었으면 빈 400.
        partial이면(/v1/guard) 인젝션 비용 상한 밖의 텍스트는 재지 않고 결과를 None으로 둔다 — 못 잰 수는 호출자가 센다."""
        state = request.app.state
        models, cache = state.models, state.cache
        clean = [LONE_SURROGATE.sub("\ufffd", t) for t in raw]

        def work() -> list[dict] | None:
            # 상한부터 모두 센다 — 한 작업을 돌린 뒤에 다른 작업의 상한에 걸리면 그 추론이 헛일이다
            if "pii_ner" in tasks:
                if sum(map(len, clean)) > MAX_CHARS:                      # 세지도 않는다
                    return None
                encs = [models["pii_ner"].encode(t) for t in clean]      # 한 번 잘라 세고, 그대로 추론에 쓴다
                if sum(len(e.ids) for e in encs) > MAX_TOKENS:
                    return None
            if "injection" in tasks:                                      # 캐시는 분류기 줄(한 번에 하나)만 만진다
                clf = models["injection"]
                keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in clean]
                # 캐시에 있는 텍스트(에이전트 루프가 단계마다 다시 보내는 도구 결과)는 세지 않는다. 캐시 밖은 새 글(뒤)부터 상한까지만 재고 캐시한다 — 상한을 넘었다고 요청 전체를
                # 거절하면 그 글이 캐시에 들지 못해 턴의 나머지 단계가 모두 413이 된다(D-127 재검증)
                todo: dict[str, tuple[str, Encoding]] = {}
                skipped: set[str] = set()
                spent = chars = 0
                for k, t in reversed(list(zip(keys, clean))):
                    if k in cache or k in todo or k in skipped:
                        continue
                    if len(t) > state.inj_tokens * 32 or chars + len(t) > MAX_CHARS:      # 상한을 넘을 게 뻔한 길이 — 토큰을 세지도 않는다
                        skipped.add(k)
                        continue
                    enc = clf.encode(t)
                    chars += len(t)
                    c = sum(b - a + len(clf.head) + len(clf.tail) + WINDOW_OVERHEAD for a, b, _, _ in windows(len(enc.ids), clf.size, clf.stride)) if enc.ids else 0
                    if spent + c > state.inj_tokens:
                        skipped.add(k)
                        continue
                    spent += c
                    todo[k] = (t, enc)
                if skipped and not partial:
                    return None
            out: list[dict] = [{} for _ in clean]
            if "pii_ner" in tasks:
                for o, t, e in zip(out, clean, encs):
                    o["pii_ner"] = models["pii_ner"].predict(t, e)
            if "injection" in tasks:
                got = {k: cache[k] for k in keys if k in cache} | {k: clf.score(t, e) for k, (t, e) in todo.items()}
                for o, k in zip(out, keys):
                    o["injection"] = got.get(k)                       # 못 잰 텍스트는 None
                    if k in got:
                        cache[k] = got[k]
                        cache.move_to_end(k)
                while len(cache) > CACHE:
                    cache.popitem(last=False)
            return out

        async with AsyncExitStack() as stack:
            for task in ("pii_ner", "injection"):                         # 늘 같은 순서로 잡는다(교착 없음)
                if task in tasks:
                    await stack.enter_async_context(state.limiters[task])
            if await request.is_disconnected():                           # 기다리는 동안 게이트웨이가 포기했다 — 줄 뒤를 막지 않는다
                return Response(status_code=400)
            return await anyio.to_thread.run_sync(work)

    @app.post("/v1/detect")
    async def detect(request: Request) -> Response:
        t0 = time.perf_counter()
        texts = await read(request, need_id=True)
        if isinstance(texts, Response):
            return texts
        loaded = list(request.app.state.models)
        tasks = request.state.req.get("tasks", loaded)
        if not isinstance(tasks, list) or not tasks or any(t not in loaded for t in tasks):
            return _error(400, "invalid_tasks", f"tasks must be a non-empty subset of {loaded}")
        found = await run(request, tasks, [t["text"] for t in texts])
        if isinstance(found, Response):
            return found
        if found is None:
            return _error(413, "too_many_tokens", "texts exceed the per-request token limit")
        return JSONResponse({"results": [{"id": t["id"], **r} for t, r in zip(texts, found)], "ms": round((time.perf_counter() - t0) * 1000, 2)})

    @app.post("/v1/guard")
    async def guard(request: Request) -> Response:
        """게이트웨이 가드레일 웹훅(D-127) — 점수는 텍스트들의 최댓값, 문턱 이상이면 block. 역할은 받기만 한다(분류는 텍스트로만)."""
        if "injection" not in request.app.state.models:
            return _error(404, "not_found", "injection task is not loaded (DETECT_INJECTION_MODEL)")
        texts = await read(request, need_id=False)
        if isinstance(texts, Response):
            return texts
        found = await run(request, ["injection"], [t["text"] for t in texts], partial=True)
        if isinstance(found, Response):
            return found
        assert found is not None                     # partial이면 상한으로 None을 돌려주지 않는다
        scored = [r["injection"] for r in found if r["injection"] is not None]
        best = max(scored, default=0.0)
        body: dict = {"verdict": "block" if best >= request.app.state.threshold else "allow", "score": best}
        if len(scored) < len(found):
            body["unscored"] = len(found) - len(scored)     # 이번에 재지 못한 텍스트 — 다음 단계에서 잰다(이미 잰 글은 캐시)
        return JSONResponse(body)

    return app


app = create_app()
