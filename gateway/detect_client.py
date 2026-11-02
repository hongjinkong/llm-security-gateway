"""탐지 사이드카 클라이언트(D-126) — 게이트웨이가 `detect/`(한국어 PII NER)에 텍스트를 보내 이름·주소·직장 구간을 받는다.

캐시: 텍스트의 SHA-256 → 구간 목록(LRU 4,096, 검사기마다). **원문은 캐시에도 없다.** 매 턴 다시 오는 이력은 캐시에서 나오고 새 메시지만 사이드카로 간다 —
결정적 대체값(D-111)과 맞물려 둘째 턴부터 이력 바이트가 같다.
묶음: 캐시에 없는 텍스트를 요청당 글자 합 MAX_CHARS(12,000) 이하로 묶는다(사이드카 상한 토큰 16,384·글자 131,072 — WordPiece는 글자당 토큰 1개를 넘지 않는다).
그보다 긴 텍스트는 MAX_CHARS 창을 OVERLAP(256)자 겹쳐 자르고, 창마다 가장자리 OVERLAP/2에서 시작하는 구간은 버린다(첫 창의 앞·마지막 창의 뒤는 빼고) —
한 구간이 두 창에서 두 번 나오지 않고, 128자보다 짧은 구간은 어느 한 창에 통째로 든다. 위치는 원래 텍스트로 옮긴다.
실패는 `DetectUnavailable(reason)` 하나다 — timeout(전체 기한 GATEWAY_DETECT_TIMEOUT)·connect·http_<상태>·bad_response. 검사기가 정책(closed·open)에 따라 503 또는 통과를 정한다.
요청은 순서대로 하나씩 보낸다 — 사이드카는 한 번에 하나만 돌린다(D-125).
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import anyio
import httpx

from gateway.detectors.patterns import NER_KINDS

MAX_CHARS = 12_000
OVERLAP = 256
MAX_TEXTS = 1024          # 사이드카의 요청당 텍스트 상한
CACHE_SIZE = 4096


@dataclass(frozen=True)
class Span:
    kind: str
    start: int
    end: int
    score: float


class DetectUnavailable(RuntimeError):
    """사이드카가 답하지 못했다(사유 코드만 — 원문·메시지 없음)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def windows(n: int) -> list[tuple[int, int, int, int]]:
    """n자 텍스트의 창 (시작, 끝, 가질 시작, 가질 끝). 가질 구간에서 **시작하는** 구간만 남기면 [0, n)의 어느 위치도 한 창만 가진다."""
    if n <= MAX_CHARS:
        return [(0, n, 0, n)]
    out: list[tuple[int, int, int, int]] = []
    start = 0
    while True:
        end = min(start + MAX_CHARS, n)
        out.append((start, end, 0 if start == 0 else start + OVERLAP // 2, n if end == n else end - OVERLAP // 2))
        if end == n:
            return out
        start = end - OVERLAP


Item = tuple[int, int, str, int, int]      # (텍스트 번호, 창 시작, 조각, 가질 시작, 가질 끝)


def batches(items: list[Item]) -> list[list[Item]]:
    """글자 합 MAX_CHARS·개수 MAX_TEXTS 이하로 묶는다(조각 하나는 MAX_CHARS 이하다)."""
    out: list[list[Item]] = []
    cur: list[Item] = []
    size = 0
    for item in items:
        if cur and (size + len(item[2]) > MAX_CHARS or len(cur) >= MAX_TEXTS):
            out.append(cur)
            cur, size = [], 0
        cur.append(item)
        size += len(item[2])
    if cur:
        out.append(cur)
    return out


class DetectClient:
    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self.url, self.timeout = url.rstrip("/"), timeout
        self._cache: OrderedDict[str, tuple[Span, ...]] = OrderedDict()
        self._client: httpx.AsyncClient | None = None

    async def prepare(self) -> None:
        self._client = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(self.timeout, connect=2.0),
                                         limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def spans(self, texts: list[str]) -> list[list[Span]]:
        """texts마다 구간 목록(위치 순, 서로 겹치지 않음). 캐시에 없는 것만 사이드카로 — 전체 기한 안에. 실패면 DetectUnavailable(캐시에는 넣지 않는다)."""
        result: list[list[Span]] = [[] for _ in texts]
        todo: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            if not text.strip():
                continue
            key = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                result[i] = list(hit)
            else:
                todo.append((i, key))
        if not todo:
            return result
        items: list[Item] = [(i, a, texts[i][a:b], own_a, own_b) for i, _ in todo for a, b, own_a, own_b in windows(len(texts[i]))]
        found: dict[int, list[Span]] = {i: [] for i, _ in todo}
        try:
            with anyio.fail_after(self.timeout):
                for batch in batches(items):
                    for (i, a, _, own_a, own_b), spans in zip(batch, await self._post(batch)):
                        found[i].extend(Span(s.kind, s.start + a, s.end + a, s.score) for s in spans if own_a <= s.start + a < own_b)
        except TimeoutError:
            raise DetectUnavailable("timeout") from None
        for i, key in todo:
            spans = sorted(found[i], key=lambda s: s.start)
            result[i] = spans
            self._cache[key] = tuple(spans)
            if len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return result

    async def _post(self, batch: list[Item]) -> list[list[Span]]:
        if self._client is None:
            await self.prepare()
        assert self._client is not None
        # 짝 없는 서로게이트는 `?`로(한 글자 대 한 글자 — 위치가 그대로다). 사이드카도 같은 길이로 본다
        body = json.dumps({"texts": [{"id": str(n), "role": "user", "text": piece} for n, (_, _, piece, _, _) in enumerate(batch)],
                           "tasks": ["pii_ner"]}, ensure_ascii=False).encode("utf-8", "replace")
        try:
            r = await self._client.post("/v1/detect", content=body, headers={"content-type": "application/json"})
        except httpx.TimeoutException:
            raise DetectUnavailable("timeout") from None
        except httpx.HTTPError:
            raise DetectUnavailable("connect") from None
        if r.status_code != 200:
            raise DetectUnavailable(f"http_{r.status_code}")
        return _parse(r, batch)


def _parse(r: httpx.Response, batch: list[Item]) -> list[list[Span]]:
    """응답의 모양·범위를 검사한다 — 어긋나면 bad_response. 제품 종류 대응이 없는 라벨(kind null)은 버린다."""
    try:
        obj: Any = r.json()
        results = obj["results"]
        if not isinstance(results, list) or len(results) != len(batch):
            raise ValueError
        out: list[list[Span]] = []
        for n, ((_, _, piece, _, _), item) in enumerate(zip(batch, results)):
            if item["id"] != str(n):
                raise ValueError
            spans: list[Span] = []
            for s in item["pii_ner"]:
                kind, start, end = s.get("kind"), s["start"], s["end"]
                if kind is None:
                    continue
                if kind not in NER_KINDS or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(piece):
                    raise ValueError
                spans.append(Span(kind, start, end, float(s.get("score", 0.0))))
            out.append(spans)
        return out
    except (ValueError, KeyError, TypeError, AttributeError):
        raise DetectUnavailable("bad_response") from None
