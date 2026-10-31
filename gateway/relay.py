"""상류 중계(D-118 — main.py에서 옮겼다): 검사기 체인 → (차단 또는) 상류 호출 → 비스트리밍 복원 또는 스트림 펌프 → 감사 줄.

상류 호출은 머리만 받고 본문은 열어 둔다 — SSE면 조각마다 흘려보내고(gateway/streaming.py), 아니면 상한까지 읽어 복원한다(D-106·D-110).
실패는 그 API의 오류 형식으로 바꾼다(D-086). 설정은 `request.app.state.settings`에서 읽는다.
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

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


@dataclass
class UpstreamClient:
    """상류 하나(D-119) — 연결 풀과 그 상류의 공급자 키. 라우트가 `request.state.upstream`에 고른다."""
    client: httpx.AsyncClient
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
        request.state.streaming = True
        return _stream_response(request, upstream, chain, session, adapter, strip_usage)

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
    client = up.client
    # 게이트웨이 요청 ID를 상류에도 — 사내 상류의 로그와 감사 줄을 잇는다(D-120). 임의 16진 16자라 공급자에게 가도 정보가 없다
    headers = [*request.app.state.auth.upstream_headers(request.url.path, request.headers.items(), up.key),
               ("x-gateway-request-id", request.state.request_id)]
    upstream_request = client.build_request(
        method=request.method,
        url=httpx.URL(path=path, query=request.url.query.encode()),
        headers=headers,
        content=body,
    )
    request.state.upstream_t0 = time.perf_counter()
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        return _upstream_failure(request, exc)
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
    """상류 호출 실패 → 그 API의 오류 형식. 풀 대기 초과는 503(상류에 보내지 않았다), 시간 초과는 504, 그 밖은 502."""
    fmt = error_format_for(request.url.path)
    request.state.upstream_error = type(exc).__name__   # 메시지는 남기지 않는다
    if isinstance(exc, httpx.PoolTimeout):
        return busy(fmt.error(503, "upstream connection pool exhausted", "upstream_error", "upstream_busy"))
    if isinstance(exc, httpx.TimeoutException):   # 상류에서 실제로 시간을 썼다. 연결조차 못 했으면 None으로 둔다.
        request.state.upstream_ms = (time.perf_counter() - request.state.upstream_t0) * 1000
        return fmt.error(504, "upstream timed out", "upstream_error", "upstream_timeout")
    return fmt.error(502, "upstream unavailable", "upstream_error", "upstream_unavailable")


def busy(response: Response) -> Response:
    response.headers["retry-after"] = "1"
    return response


def _pass_headers(upstream: httpx.Response, response: Response) -> None:
    """허용 목록의 상류 응답 헤더만 옮긴다(D-109). 같은 이름이 여럿이면 각각 보존한다(D-102)."""
    for name, value in upstream.headers.multi_items():
        if name.lower() in PASS_RESPONSE_HEADERS:
            response.headers.append(name, value)


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


def _stream_response(request: Request, upstream: httpx.Response, chain: DetectorChain,
                     session: str, adapter: Adapter, strip_usage: bool) -> StreamingResponse:
    """상류 SSE를 조각마다 흘려보낸다(D-106). 복원은 pii_mask 검사기의 볼트로, 감사 줄·볼트 해제는 스트림 끝에서.
    스트림 모양은 어댑터가 준다(D-107 C). usage는 이벤트에서 모은다(D-120)."""
    pii = next((d for d in chain.detectors if isinstance(d, PIIDetector)), None)    # detect 모드도 새 PII를 센다(D-120)
    if pii is not None and pii.mode == "mask" and pii.vault.issued(session):
        restore = lambda text, escape=None: pii.vault.restore(session, text, escape)   # noqa: E731
        hold = lambda text: pii.vault.hold(session, text)                              # noqa: E731
    else:
        restore, hold = (lambda text, escape=None: (text, 0)), (lambda text: 0)       # 발급한 대체값이 없으면 손대지 않는다
    restorer = StreamRestorer(adapter.stream_shape(), restore, hold, adapter.usage_raw, _usage_only if strip_usage else None)
    response = StreamingResponse(iter(()), status_code=upstream.status_code)
    response.body_iterator = _pump(request, upstream, chain, session, restorer, pii, adapter, response)
    _pass_headers(upstream, response)
    if pii is not None and pii.vault.issued(session):
        response.headers["x-gateway-pii"] = f"issued={pii.vault.issued(session)}"   # 머리가 본문보다 먼저 나간다 — 복원 수는 감사에만(D-113)
    return response


async def _pump(request: Request, upstream: httpx.Response, chain: DetectorChain, session: str,
                restorer: StreamRestorer, pii: PIIDetector | None, adapter: Adapter,
                response: Response) -> AsyncIterator[bytes]:
    """조각을 복원해 내보내고, 어떻게 끝나든(정상·상류 끊김·클라이언트 취소) 감사 줄을 정확히 한 줄 쓴다."""
    state = request.state
    t0 = state.upstream_t0
    size, error = 0, None
    try:
        async for data in upstream.aiter_bytes():
            if pii is not None:
                pii.vault.touch(session)     # ping·thinking만 오는 동안에도 매핑이 만료되지 않게(D-110)
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
            state.usage = adapter.usage(restorer.usage_raw) if restorer.usage_raw else None
            state.response_steps = _stream_steps(session, restorer, pii)
            if session == state.request_id:
                await chain.release(session)
        finally:
            request.app.state.audit.write(record(
                request, response, (time.perf_counter() - state.t0) * 1000, error=error, res_bytes=size))


def _stream_steps(session: str, restorer: StreamRestorer, pii: PIIDetector | None) -> list[Step]:
    """스트림이 끝난 뒤의 응답 기록. 스트림에서 실제로 복원한 건수와 내보낸 출력 전체의 잔여 대체값·의심·새 PII —
    감사는 사용자가 받은 것을 적는다(D-106·D-120). 응답 경로의 검사기는 PII 하나다(D-109)."""
    if pii is None:
        return []
    stats = pii.response_stats(session, restorer.visible_text)
    issued = pii.mode == "mask" and pii.vault.issued(session)
    if not issued:
        return [Step(pii.name, "restore", 0.0, "", {"new": stats["new"]})] if stats["new"] else []
    return [Step(pii.name, "restore", 0.0, "", {"restored": restorer.restored, "issued": pii.vault.issued(session), **stats})]


def _as_text(content: bytes, content_type: str) -> str | None:
    """텍스트 응답만 후처리한다. 이미지·바이너리는 손대지 않는다."""
    ct = content_type.lower()
    if "json" not in ct and not ct.startswith("text/") and "xml" not in ct:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
