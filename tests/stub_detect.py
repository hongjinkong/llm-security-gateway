"""시험용 탐지 사이드카(D-126·D-127) — onnxruntime 없이 **규칙**으로 `detect/`의 계약(`POST /v1/detect`·`POST /v1/guard`·`GET /health`)을 흉내 낸다. 게이트웨이 코드가 아니다.

이름은 사전(`NAMES`)의 글자열, 주소는 시·도로 시작하는 꼴(`ADDRESS_RE`), 직장은 사전(`ORGS`)이다. 텍스트 속 지시 문구로 실패를 만든다:
  @@500@@ → 500 · @@sleep@@ → 3초 뒤 답 · @@garbage@@ → JSON이 아닌 200 · @@phone-as-org@@ → 전화번호 꼴을 직장으로 보고(정규식 우선 확인)
받은 요청의 텍스트 수는 포트별로 `/__stub/calls`에 남는다(캐시 적중 확인).
가드레일(`/v1/guard`): @@inject@@가 든 텍스트가 있으면 block 0.99, 아니면 allow 0.01. 위 실패 문구와 @@badscore@@(점수 2)·@@hugescore@@(400자리 정수 점수)·
@@400@@·@@413@@·@@422@@(입력 거절)·@@deep@@(깊게 중첩된 JSON)도 같다. @@unscored@@면 allow인데 `unscored: 2`. 받은 texts는 포트별로 `/__stub/guard`.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()
CALLS: defaultdict[int, list[int]] = defaultdict(list)       # 포트 → 요청마다 받은 텍스트 수
NAMES = ("김철수", "이영희", "박민준", "최지우", "홍길동", "Sarah Kim")
ORGS = ("한빛소프트", "삼성전자")
ADDRESS_RE = re.compile(r"(?:서울특별시|서울|경기도|경기|부산광역시|부산|대전광역시|대전)(?: [가-힣]+(?:시|구|군))*"
                        r"(?: [가-힣]+(?:로|길) \d+(?:-\d+)?(?:,? \d+층)?(?: \d+호)?)?")
PHONE_RE = re.compile(r"01\d-\d{4}-\d{4}")


def spans_of(text: str) -> list[dict]:
    found: list[tuple[int, int, str, str]] = []
    for name in NAMES:
        for m in re.finditer(re.escape(name), text):
            found.append((m.start(), m.end(), "PERSON", "person"))
    for org in ORGS:
        for m in re.finditer(re.escape(org), text):
            found.append((m.start(), m.end(), "ORGANIZATION", "org"))
    for m in ADDRESS_RE.finditer(text):
        found.append((m.start(), m.end(), "ADDRESS", "address"))
    if "@@phone-as-org@@" in text:
        for m in PHONE_RE.finditer(text):
            found.append((m.start(), m.end(), "ORGANIZATION", "org"))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out: list[dict] = []
    for s, e, label, kind in found:
        if out and s < out[-1]["end"]:
            continue
        out.append({"start": s, "end": e, "label": label, "kind": kind, "score": 0.97})
    return out


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tasks": {"pii_ner": {"model": "stub", "revision": "0" * 40, "license": "Apache-2.0", "sha256": "0" * 64}}}


@app.get("/__stub/calls")
async def calls(request: Request) -> dict:
    return {"calls": CALLS[request.scope["server"][1]]}


@app.post("/v1/detect")
async def detect(request: Request) -> Response:
    req = json.loads(await request.body())
    texts = req["texts"]
    CALLS[request.scope["server"][1]].append(len(texts))
    joined = "".join(t["text"] for t in texts)
    if "@@sleep@@" in joined:
        await asyncio.sleep(3)
    if "@@500@@" in joined:
        return JSONResponse({"error": {"code": "boom", "message": "stub failure"}}, status_code=500)
    if "@@garbage@@" in joined:
        return Response(b"not json", media_type="application/json")
    return JSONResponse({"results": [{"id": t["id"], "pii_ner": spans_of(t["text"])} for t in texts], "ms": 1.0})


GUARD: defaultdict[int, list[list[dict]]] = defaultdict(list)     # 포트 → 요청마다 받은 texts


@app.get("/__stub/guard")
async def guard_calls(request: Request) -> dict:
    return {"calls": GUARD[request.scope["server"][1]]}


@app.post("/v1/guard")
async def guard(request: Request) -> Response:
    texts = json.loads(await request.body())["texts"]
    GUARD[request.scope["server"][1]].append(texts)
    joined = "".join(t["text"] for t in texts)
    if "@@sleep@@" in joined:
        await asyncio.sleep(3)
    if "@@500@@" in joined:
        return JSONResponse({"error": {"code": "boom", "message": "stub failure"}}, status_code=500)
    if "@@garbage@@" in joined:
        return Response(b"not json", media_type="application/json")
    if "@@badscore@@" in joined:
        return JSONResponse({"verdict": "block", "score": 2})
    if "@@deep@@" in joined:
        return Response(b'{"verdict": ' + b"[" * 100_000 + b"]" * 100_000 + b"}", media_type="application/json")
    if "@@unscored@@" in joined:
        return JSONResponse({"verdict": "allow", "score": 0.01, "unscored": 2})
    if "@@hugescore@@" in joined:
        return Response(b'{"verdict": "block", "score": 1' + b"0" * 400 + b"}", media_type="application/json")
    for code in (400, 413, 422):
        if f"@@{code}@@" in joined:
            return JSONResponse({"error": {"code": "too_big", "message": "stub rejects the input"}}, status_code=code)
    return JSONResponse({"verdict": "block", "score": 0.99} if "@@inject@@" in joined else {"verdict": "allow", "score": 0.01})
