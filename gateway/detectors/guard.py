"""가드레일 웹훅 검사기(D-127) — 이번 턴의 사용자 글·도구 결과·첨부 문서를 운영자가 정한 가드레일(`GATEWAY_GUARD_URL`)에 보내 판정을 받는다.

  POST GATEWAY_GUARD_URL  {"texts": [{"role": "user"|"tool", "text": …}]}  →  200 {"verdict": "allow"|"block", "score": 0~1[, "unscored": 재지 못한 텍스트 수]}   (그 밖의 키는 무시)

텍스트는 메시지마다 하나로 잇는다(파트가 몇 개든 메시지 수만큼). role은 사용자 글이 user, 도구 결과와 이번 턴의 첨부 문서(Anthropic document)가 tool이다 — 모델의 답(assistant)·
system 프롬프트·이전 턴은 보내지 않는다. 이번 턴은 **글이 든** 마지막 user 메시지부터다 — 빈 user 메시지나 그림만 든 user 메시지를 덧붙여 판정할 글을 이력으로 밀어내지 못한다(D-127 재검증). 체인의 마지막(PII 뒤)에 선다 — 웹훅은 공급자가 받을 것과 같은 텍스트를 본다: 정책이 가리는 종류만 가짜 값이고
감사만 종류·켜지 않은 종류(이름·주소는 기본 꺼짐)와 detect·off 정책의 텍스트는 원문 그대로다(D-127 리뷰).
  observe(`injection_guard`)        막지 않는다. 감사 줄에 guard_verdict·guard_score, block 판정이면 would_block.
  block(`injection_guard_block`)    block 판정이면 룰 차단과 같은 200 차단 응답(사유는 감사에만 — 역산당하지 않게, D-040).
실패(guard_error: timeout·connect·http_<상태>·bad_response)는 observe면 판정 없이 통과한다. block에서 웹훅이 **입력을 거절**하거나(400·413·422 — 너무 크거나 많다) 일부를 재지
못했다고 하면(`unscored`) GATEWAY_GUARD_FAIL과 상관없이 막는다 — 통과시키면 글을 부풀리기만 해도 판정을 피한다(D-127 리뷰). 그 밖의 실패는 open이면 통과, closed면 503 guard_unavailable.
탐지 사이드카(detect/)의 POST /v1/guard가 이 계약을 구현한다(인젝션 분류기, D-127).
"""
from __future__ import annotations

import json
import math
from typing import Any

import anyio
import httpx

from gateway.api.base import ApiError
from gateway.detectors.base import Detector, Inspection, Verdict

MODES = ("observe", "block")
FAIL_MODES = ("open", "closed")
INPUT_REJECTED = frozenset({"http_400", "http_413", "http_422"})     # 웹훅이 입력 때문에 거절했다 — block이면 막는다


def turn_texts(doc) -> list[dict]:
    """이번 턴의 사용자 글·도구 결과·첨부 문서 — 같은 메시지의 이어진 파트는 하나로 잇는다. 모델의 답(assistant)과 빈 글은 뺀다.
    system 역할 텍스트는 user 메시지 안에 든 것(Anthropic 첨부 문서)만 보낸다 — 마지막 user 메시지 뒤에 놓인 system·developer 메시지는 운영자의 지시라 보내지 않는다(D-127 재검증)."""
    items = doc.payload.get("messages") if isinstance(doc.payload.get("messages"), list) else doc.payload.get("input")

    def owner(msg: int) -> object:
        return items[msg].get("role") if isinstance(items, list) and 0 <= msg < len(items) and isinstance(items[msg], dict) else None
    refs = [r for r in doc.texts() if r.msg >= 0 and r.role != "assistant" and (r.role != "system" or owner(r.msg) == "user")]
    # 이번 턴 = 글이 든 마지막 user 메시지부터(어댑터의 turn은 빈 user 메시지에서도 시작한다)
    start = max((r.msg for r in refs if r.role == "user" and r.get().strip()), default=min((r.msg for r in refs if r.turn), default=0))
    out: list[dict] = []
    last: tuple[int, str] | None = None
    for r in refs:
        if r.msg < start or not (text := r.get()).strip():
            continue
        role = "user" if r.role == "user" else "tool"
        if out and last == (r.msg, role):
            out[-1]["text"] += "\n" + text
        else:
            out.append({"role": role, "text": text})
            last = (r.msg, role)
    return out


class GuardDetector(Detector):
    def __init__(self, url: str, mode: str = "observe", timeout: float = 5.0, fail: str = "open") -> None:
        if mode not in MODES or fail not in FAIL_MODES:
            raise ValueError(f"mode는 {MODES}, fail은 {FAIL_MODES} 중 하나다: {mode!r} {fail!r}")
        self.url, self.mode, self.timeout, self.fail = url, mode, timeout, fail
        self.name = "injection_guard" if mode == "observe" else "injection_guard_block"
        self._client: httpx.AsyncClient | None = None

    async def prepare(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=min(2.0, self.timeout)),
                                         # 쉬는 연결은 4초 뒤 버린다 — 웹훅 서버(uvicorn 기본 5초)가 닫는 순간 그 연결로 보내지 않게(D-122와 같은 이유)
                                         limits=httpx.Limits(max_connections=16, max_keepalive_connections=16, keepalive_expiry=4))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def inspect(self, insp: Inspection) -> Verdict:
        texts = turn_texts(insp.doc)
        if not texts:
            return Verdict.allow(self.name)
        got = await self._ask(texts)
        if isinstance(got, str):                     # 실패 사유
            if self.mode == "block" and got in INPUT_REJECTED:
                return Verdict.block(self.name, "가드레일이 판정하지 못한 입력", guard_error=got)
            if self.mode == "block" and self.fail == "closed":
                raise ApiError("guardrail is unavailable", None, "guard_unavailable", 503, "overloaded_error",
                               meta={"detector": self.name, "guard_error": got})
            return Verdict.allow(self.name, guard_error=got)
        verdict, score, unscored = got
        meta: dict[str, Any] = {"guard_verdict": verdict, "guard_score": score}
        if unscored:
            meta["guard_unscored"] = unscored                   # 웹훅이 재지 못한 텍스트 수(상한) — 그 글은 판정 없이 간다
        if verdict == "block" or (unscored and self.mode == "block"):
            if self.mode == "block":
                return Verdict.block(self.name, "가드레일 차단" if verdict == "block" else "가드레일이 판정하지 못한 입력", **meta)
            meta["would_block"] = True
        return Verdict.allow(self.name, **meta)

    async def _ask(self, texts: list[dict]) -> tuple[str, float, int] | str:
        """(판정, 점수) 또는 실패 사유. 전체 기한은 GATEWAY_GUARD_TIMEOUT — httpx의 시간 제한은 단계마다라 느리게 흘리는 응답을 끊지 못한다."""
        if self._client is None:
            await self.prepare()
        assert self._client is not None
        # 짝 없는 서로게이트(JSON "\ud800")는 '?'로 — UTF-8로 못 쓰면 요청이 500이 된다(D-124와 같은 이유)
        body = json.dumps({"texts": texts}, ensure_ascii=False).encode("utf-8", "replace")
        try:
            with anyio.fail_after(self.timeout):
                r = await self._client.post(self.url, content=body, headers={"content-type": "application/json"})
        except (TimeoutError, httpx.TimeoutException):
            return "timeout"
        except (httpx.HTTPError, httpx.InvalidURL):
            return "connect"
        if r.status_code != 200:
            return f"http_{r.status_code}"
        try:
            obj = r.json()
            verdict, score, unscored = obj["verdict"], obj["score"], obj.get("unscored", 0)
            ok = (verdict in ("allow", "block") and type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1
                  and type(unscored) is int and unscored >= 0)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):   # 400자리 정수 점수·깊은 중첩도 bad_response(500이 아니다)
            return "bad_response"
        return (verdict, round(float(score), 6), unscored) if ok else "bad_response"
