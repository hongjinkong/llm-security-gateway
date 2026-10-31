"""상류 중계(D-118 — main.py에서 옮겼다): 검사기 체인 → (차단 또는) 상류 호출 → 비스트리밍 복원 또는 스트림 펌프 → 감사 줄.

상류 호출은 머리만 받고 본문은 열어 둔다 — SSE면 조각마다 흘려보내고(gateway/streaming.py), 아니면 상한까지 읽어 복원한다(D-106·D-110).
실패는 그 API의 오류 형식으로 바꾼다(D-086). 설정은 `request.app.state.settings`에서 읽는다.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import anyio
import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from gateway.api import ApiError, Doc, error_format_for
from gateway.api.base import Adapter
from gateway.audit import pii_fields, record
from gateway.chain import DetectorChain, Step
from gateway.detectors.base import Inspection
from gateway.detectors.pii import PIIDetector
from gateway.messages import t
from gateway.streaming import StreamRestorer
from gateway.vault import VaultFull

# D-109: 클라이언트에 넘기는 상류 응답 헤더. 그 밖(set-cookie·openai-organization·레이트리밋·요청 ID·hop-by-hop·
# content-encoding·content-length·date·server)은 전부 뗀다. 요청 헤더의 허용 목록은 gateway/auth.py에 있다.
PASS_RESPONSE_HEADERS = frozenset({"content-type", "cache-control", "retry-after", "retry-after-ms", "x-should-retry"})
MAX_RESPONSE_BYTES = 32 * 1024 * 1024      # 비스트리밍 상류 응답 상한(D-110) — 넘으면 502


class UpstreamPool:
    """상류 하나의 연결들(D-122) — 연결 하나짜리 httpx 클라이언트를 빌려 쓰고 돌려준다. 최근에 돌려준 것부터 다시 쓴다(LIFO).

    클라이언트 하나를 함께 쓰면 httpcore 1.0.9가 기다리는 요청 여럿에게 같은 유휴 연결을 배정한다(배정이 연결을 예약하지 않는다) —
    하나만 쓰고 나머지는 다시 줄을 선다. 동시 100에서 초당 35건만 끝났고(이론 300) 나머지 연결은 놀다가 서버 keep-alive에 닫혔다.
    빌리고 돌려주면 한 연결에 요청이 겹치지 않는다(같은 부하에서 초당 303건, 1초 넘는 요청 0).
    다 빌려 갔으면 먼저 온 요청부터 받는다 — 돌려받은 연결은 기다리는 요청에게 바로 넘긴다(새로 온 요청이 가로채지 않는다).
    첫 연결은 만들 때 만든다: 클라이언트를 만들 수 없는 설정(프록시 환경변수·주소 오류)이면 기동이 실패한다.
    """

    def __init__(self, make: Callable[[], httpx.AsyncClient], size: int, wait: float) -> None:
        self._make, self._size, self._wait = make, size, wait
        self._made: list[httpx.AsyncClient] = [make()]
        self._idle: list[httpx.AsyncClient] = list(self._made)
        self._waiters: deque[asyncio.Future[httpx.AsyncClient]] = deque()

    @property
    def in_use(self) -> int:
        return len(self._made) - len(self._idle)

    @property
    def base_url(self) -> str:
        return str(self._made[0].base_url).rstrip("/")

    async def acquire(self) -> httpx.AsyncClient:
        """빈 연결이 없고 다 만들었으면 `wait`초 기다린다 — 넘으면 TimeoutError(503 upstream_busy)."""
        if self._idle and not self._waiters:
            return self._idle.pop()
        if len(self._made) < self._size:
            self._made.append(self._make())
            return self._made[-1]
        waiter: asyncio.Future[httpx.AsyncClient] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            return await asyncio.wait_for(waiter, self._wait)
        except BaseException:
            if waiter.done() and not waiter.cancelled():      # 넘겨받은 순간 시간이 다 됐거나 취소됐다 — 다음 사람에게
                self.release(waiter.result())
            elif waiter in self._waiters:
                self._waiters.remove(waiter)
            raise

    def release(self, client: httpx.AsyncClient) -> None:
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(client)
                return
        self._idle.append(client)

    async def aclose(self) -> None:
        for client in self._made:
            await client.aclose()


class _Returning(httpx.AsyncByteStream):
    """응답 본문을 닫을 때 빌린 연결을 풀에 돌려준다(D-122). 두 번 닫혀도 한 번만 돌려준다."""

    def __init__(self, stream: httpx.AsyncByteStream, release: Callable[[], None]) -> None:
        self._stream = stream
        self._release: Callable[[], None] | None = release

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        try:
            await self._stream.aclose()
        finally:
            release, self._release = self._release, None
            if release is not None:
                release()


@dataclass
class UpstreamClient:
    """상류 하나(D-119) — 연결 풀과 그 상류의 공급자 키. 라우트가 `request.state.upstream`에 고른다."""
    pool: UpstreamPool
    key: str


async def read_body(request: Request, limit: int) -> tuple[bytes | None, int]:
    """(본문, 바이트 수). 상한을 넘으면 본문 대신 None.

    넘은 뒤에도 끝까지 읽어서 버린다 — 읽다 말고 응답하면 클라이언트가 413 대신 연결 오류를
    받는다. 버리는 동안 쌓지 않으므로 메모리는 상한까지만 쓴다.
    """
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size <= limit:
            chunks.append(chunk)
    return (b"".join(chunks) if size <= limit else None), size


async def relay(request: Request, body: bytes, doc: Doc, chain: DetectorChain, session: str) -> Response:
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
        return busy(adapter.error(503, "gateway is at capacity", "overloaded_error", "gateway_busy"))
    request.state.chain_result = result
    wants_stream = adapter.wants_stream(doc.payload)
    if result.blocked:
        request.state.blocked = True
        # 차단 시 상류를 호출하지 않는다 → upstream_ms는 None으로 남는다.
        # 차단 사유는 응답에 넣지 않는다(D-040). 요청 ID만 넣는다 — 사용자가 운영자에게 물을 수 있는 손잡이다(D-107 E).
        s = request.app.state.settings
        message = t("request_id", s.lang, message=s.blocked_message or t("blocked", s.lang), id=request.state.request_id)
        return adapter.blocked(doc.payload, request.state.request_id, message, wants_stream)

    body = result.body                                   # TRANSFORM이 있었으면 바뀐 본문
    strip_usage = False
    if wants_stream:                                     # Chat 스트림은 요청해야 usage를 준다(D-120)
        body, strip_usage = adapter.with_stream_usage(body)
    upstream = await send(request, adapter.upstream_path(), body)
    if not isinstance(upstream, httpx.Response):
        return upstream
    if wants_stream and _is_sse(upstream):
        try:
            stream = _stream_response(request, upstream, chain, session, adapter, strip_usage)
        except BaseException:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()
            raise
        request.state.streaming = True                   # 이제부터 감사 줄·볼트 해제는 스트림이 한다
        request.state.stream_finish = stream.finish      # 응답이 돌기 전에 요청이 끝나면 미들웨어가 부른다(D-122)
        return stream

    # SSE가 아니면(비스트리밍, 상류 오류 JSON, 스트리밍을 무시하는 상류) 상한까지 읽어 비스트리밍 후처리로 보낸다(D-106·D-110).
    content = await read_capped(request, upstream)
    if not isinstance(content, bytes):
        return content
    text = _as_text(content, upstream.headers.get("content-type", ""))
    if text is not None:
        request.state.usage = _usage(adapter, text)
        restored, steps = await chain.run_response(session, text)
        if steps:
            request.state.response_steps = steps
        if restored != text:
            content = restored.encode("utf-8")
    response = downstream(upstream, content)
    pii = pii_fields(request.state.response_steps)
    if pii["pii_issued"]:
        response.headers["x-gateway-pii"] = f"issued={pii['pii_issued']} restored={pii['pii_restored']}"
    return response


async def send(request: Request, path: str, body: bytes | None) -> httpx.Response | Response:
    """상류 호출. 헤더는 허용 목록만(D-109, auth.upstream_headers). 머리만 받고 본문은 열어 둔다 — 호출자가 SSE면 흘려보내고
    아니면 `_read_capped`로 읽는다. 실패는 그 API의 오류 형식 응답으로 바꿔 돌려준다(D-086·D-110)."""
    up: UpstreamClient = request.state.upstream
    # 게이트웨이 요청 ID를 상류에도 — 사내 상류의 로그와 감사 줄을 잇는다(D-120). 임의 16진 16자라 공급자에게 가도 정보가 없다
    headers = [*request.app.state.auth.upstream_headers(request.url.path, request.headers.items(), up.key),
               ("x-gateway-request-id", request.state.request_id)]
    request.state.upstream_t0 = time.perf_counter()
    try:
        client = await up.pool.acquire()
    except TimeoutError:                     # 빈 연결을 기다리다 시간이 다 됐다 — 상류에 보내지 않았다
        request.state.upstream_error = "upstream_busy"
        return busy(error_format_for(request.url.path).error(
            503, "upstream connection pool exhausted", "upstream_error", "upstream_busy"))
    try:
        upstream_request = client.build_request(
            method=request.method,
            url=httpx.URL(path=path, query=request.url.query.encode()),
            # 받은 바이트 그대로 넘긴다 — Starlette는 헤더를 latin-1로 풀고 httpx는 str을 ascii로 묶어, 비ASCII 값(한국어 User-Agent)이면 오류다
            headers=[(k, v.encode("latin-1")) for k, v in headers],
            content=body,
        )
        upstream = await client.send(upstream_request, stream=True)
    except BaseException as exc:             # 요청 만들기·보내기·취소(클라이언트가 끊음) — 무엇이든 빌린 연결을 돌려준다(D-122)
        up.pool.release(client)
        if isinstance(exc, httpx.RequestError):
            return _upstream_failure(request, exc)
        raise
    assert isinstance(upstream.stream, httpx.AsyncByteStream)
    upstream.stream = _Returning(upstream.stream, lambda: up.pool.release(client))   # 본문을 닫을 때(read_capped·_pump) 돌려준다
    request.state.upstream_request_id = upstream.headers.get("x-request-id") or upstream.headers.get("request-id")
    return upstream


async def read_capped(request: Request, upstream: httpx.Response) -> bytes | Response:
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
    """상류 호출 실패 → 그 API의 오류 형식. 시간 초과는 504, 그 밖은 502. 풀 대기 초과(503)는 `send`가 연결을 빌릴 때 낸다(D-122)."""
    fmt = error_format_for(request.url.path)
    request.state.upstream_error = type(exc).__name__   # 메시지는 남기지 않는다
    if isinstance(exc, httpx.TimeoutException):   # 상류에서 실제로 시간을 썼다. 연결조차 못 했으면 None으로 둔다.
        request.state.upstream_ms = (time.perf_counter() - request.state.upstream_t0) * 1000
        return fmt.error(504, "upstream timed out", "upstream_error", "upstream_timeout")
    return fmt.error(502, "upstream unavailable", "upstream_error", "upstream_unavailable")


def busy(response: Response) -> Response:
    response.headers["retry-after"] = "1"
    return response


def _pass_headers(upstream: httpx.Response, response: Response) -> None:
    """허용 목록의 상류 응답 헤더만 옮긴다(D-109). 같은 이름이 여럿이면 각각 보존한다(D-102)."""
    for name, value in upstream.headers.raw:             # 받은 바이트 그대로 — 비latin-1 값을 str로 다시 묶다 오류가 나지 않게(D-122)
        if name.decode("latin-1").lower() in PASS_RESPONSE_HEADERS:
            response.raw_headers.append((name.lower(), value))


def downstream(upstream: httpx.Response, content: bytes) -> Response:
    response = Response(content=content, status_code=upstream.status_code)
    _pass_headers(upstream, response)
    return response


def _is_sse(upstream: httpx.Response) -> bool:
    return upstream.headers.get("content-type", "").lower().startswith("text/event-stream")


def _usage(adapter: Adapter, text: str) -> dict | None:
    """비스트리밍 응답 JSON의 usage(D-120). JSON이 아니거나 usage가 없으면 None."""
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    return adapter.usage(adapter.usage_raw(obj)) if isinstance(obj, dict) else None


def _usage_only(obj: dict) -> bool:
    """Chat의 usage 조각(`choices: []`) — 게이트웨이가 요청했고 클라이언트는 요청하지 않았으면 내보내지 않는다(D-120)."""
    return obj.get("choices") == [] and obj.get("usage") is not None


class _Stream(StreamingResponse):
    """스트리밍 응답(D-122). 본문을 한 번도 돌리지 못하고 끝나도(머리를 보내다 클라이언트가 끊어 취소) 마무리를 한 번 한다 —
    본문 생성기는 시작되지 않으면 finally도 돌지 않는다."""

    finish: Callable[[str | None], Awaitable[None]]
    completed: list[bool]                                # 본문 생성기가 마지막 조각까지 넘겼는가

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        error = None
        try:
            await super().__call__(scope, receive, send)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            # uvicorn은 ASGI 2.3이라 Starlette가 끊김을 작업 취소로 처리하고 삼킨다 — 예외 없이 끝났어도 본문이 끝나지 않았으면 끊긴 것이다
            await self.finish(error or (None if self.completed[0] else "ClientDisconnect"))


def _stream_response(request: Request, upstream: httpx.Response, chain: DetectorChain,
                     session: str, adapter: Adapter, strip_usage: bool) -> _Stream:
    """상류 SSE를 조각마다 흘려보낸다(D-106). 복원은 pii_mask 검사기의 볼트로, 감사 줄·볼트 해제는 스트림 끝에서.
    스트림 모양은 어댑터가 준다(D-107 C). usage는 이벤트에서 모은다(D-120)."""
    pii = next((d for d in chain.detectors if isinstance(d, PIIDetector)), None)    # detect 모드도 새 PII를 센다(D-120)
    if pii is not None and pii.mode == "mask" and pii.vault.issued(session):
        restore = lambda text, escape=None: pii.vault.restore(session, text, escape)   # noqa: E731
        hold = lambda text: pii.vault.hold(session, text)                              # noqa: E731
    else:
        restore, hold = (lambda text, escape=None: (text, 0)), (lambda text: 0)       # 발급한 대체값이 없으면 손대지 않는다
    restorer = StreamRestorer(adapter.stream_shape(), restore, hold, adapter.usage_raw, _usage_only if strip_usage else None)
    response = _Stream(iter(()), status_code=upstream.status_code)
    state, sent = request.state, [0]                     # sent: 내보낸 바이트(감사 res_bytes)
    finished = False

    async def finish(error: str | None) -> None:
        """상류 닫기·usage·응답 기록·볼트 해제·감사 한 줄 — 어떻게 끝나든 정확히 한 번(D-106·D-122).
        클라이언트가 끊으면 이 작업은 anyio로 취소되고, 그 취소는 정리 중의 await마다 다시 터진다 — 취소를 막고 끝까지 한다."""
        nonlocal finished
        if finished:
            return
        finished = True
        state.upstream_ms = (time.perf_counter() - state.upstream_t0) * 1000   # 첫 바이트가 아니라 스트림 끝까지
        with anyio.CancelScope(shield=True):
            try:
                await upstream.aclose()
                state.usage = adapter.usage(restorer.usage_raw) if restorer.usage_raw else None
                state.response_steps = _stream_steps(session, restorer, pii)
                if session == state.request_id:
                    await chain.release(session)
            finally:
                request.app.state.audit.write(record(
                    request, response, (time.perf_counter() - state.t0) * 1000, error=error, res_bytes=sent[0]))

    response.finish, response.completed = finish, [False]
    response.body_iterator = _pump(upstream, session, restorer, pii, finish, sent, response.completed)
    _pass_headers(upstream, response)
    if pii is not None and pii.vault.issued(session):
        response.headers["x-gateway-pii"] = f"issued={pii.vault.issued(session)}"   # 머리가 본문보다 먼저 나간다 — 복원 수는 감사에만(D-113)
    return response


async def _pump(upstream: httpx.Response, session: str, restorer: StreamRestorer, pii: PIIDetector | None,
                finish: Callable[[str | None], Awaitable[None]], sent: list[int], completed: list[bool]) -> AsyncIterator[bytes]:
    """조각을 복원해 내보낸다. 끝나면(정상·상류 끊김·클라이언트 취소) `finish`가 감사 줄을 정확히 한 줄 쓴다.
    `sent`는 넘겨준 뒤에 센다 — yield에서 돌아왔다는 것은 응답이 그 조각을 보냈다는 뜻이다."""
    error = None
    try:
        async for data in upstream.aiter_bytes():
            if pii is not None:
                pii.vault.touch(session)     # ping·thinking만 오는 동안에도 매핑이 만료되지 않게(D-110)
            out = restorer.feed(data)
            if out:
                yield out
                sent[0] += len(out)
        out = restorer.finish()
        if out:
            yield out
            sent[0] += len(out)
        completed[0] = True
        if restorer.failed:
            error = "upstream_stream_error"     # 상류가 머리(200) 뒤 스트림 안에 보낸 오류 이벤트(D-124) — 예외가 아니어도 상류 오류로 센다
    except BaseException as exc:
        # 메시지는 남기지 않는다. 상류 오류 이벤트 뒤의 끊김(SDK가 오류를 받고 닫음)은 상류 오류로 센다 — 먼저 일어난 원인(D-124)
        error = "upstream_stream_error" if restorer.failed else type(exc).__name__
        raise
    finally:
        await finish(error)


def _stream_steps(session: str, restorer: StreamRestorer, pii: PIIDetector | None) -> list[Step]:
    """스트림이 끝난 뒤의 응답 기록. 스트림에서 실제로 복원한 건수와 조각으로 내보낸 텍스트의 잔여 대체값·의심·새 PII —
    감사는 사용자가 받은 것을 적는다(D-106·D-120). 응답 경로의 검사기는 PII 하나다(D-109).
    복원 수는 조각에서 센 수와 끝 이벤트(응답 전체)에서 센 수 중 큰 쪽이다(D-124) — 델타 없이 done·completed로만 온 값도 센다.
    잔여·의심·새 PII는 조각 텍스트에서만 센다 — 델타 없이 끝 이벤트로만 온 텍스트는 세지 않는다(D-124 §5)."""
    if pii is None:
        return []
    stats = pii.response_stats(session, restorer.visible_text)
    issued = pii.mode == "mask" and pii.vault.issued(session)
    if not issued:
        return [Step(pii.name, "restore", 0.0, "", {"new": stats["new"]})] if stats["new"] else []
    restored = max(restorer.restored, restorer.final_restored)
    return [Step(pii.name, "restore", 0.0, "", {"restored": restored, "issued": pii.vault.issued(session), **stats})]


def _as_text(content: bytes, content_type: str) -> str | None:
    """텍스트 응답만 후처리한다. 이미지·바이너리는 손대지 않는다."""
    ct = content_type.lower()
    if "json" not in ct and not ct.startswith("text/") and "xml" not in ct:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
