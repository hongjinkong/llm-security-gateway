"""가짜 상류(공급자) — 게이트웨이를 검증하기 위한 도구. 게이트웨이 코드가 아니다.

핵심은 '받은 것을 그대로 되돌려주는' 필드(gateway_test·echo)와 실제 수신 기록(/__stub/received·/__stub/hits)이다.
이게 있어야 프록시가 요청을 망가뜨렸는지, 무엇이 상류에 닿았는지 비교로 확인할 수 있다.
"""
import asyncio
import json
import os
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from gateway.detectors.patterns import find_all

app = FastAPI(title="stub target")

# D-122: 부하 측정용 지연 — 첫 바이트 전(POST)과 스트림 조각 사이(초). 환경변수가 없으면 0이라 테스트는 예전과 같다.
DELAY = float(os.environ.get("STUB_DELAY_MS", "0")) / 1000
CHUNK = float(os.environ.get("STUB_CHUNK_MS", "0")) / 1000

# D-107 B: 게이트웨이는 토큰이 아니라 같은 모양의 대체값을 보낸다. "가려진 것을 봤다"는 **PII 모양의 값이 있는데 테스트의
# 합성 원문이 아니다**로 판정한다. 테스트가 쓰는 합성 값의 조각 목록이다 — 새 값을 테스트에 들이면 여기에도 더한다.
# D-120: usage 매핑 확인용(캐시 항목 포함)
CHAT_USAGE = {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8, "prompt_tokens_details": {"cached_tokens": 1}}
RAW_MARKERS = ("2345-6789", "1234-5678", "1111-2222", "5566-7788", "9876-5432", "1122-3344", "123-4567", "1234563",
               "1234567", "1456782", "2345671", "4111-1111", "A1b2C3d4", "ABCDEFGHIJKLMNOP", "system@example.com",
               "rag@example.com", "kim@example.com", "kim.synthetic@example.com",
               "hanbit-tech.example", "2345\n6789", "2345\t6789")


def thinking_sig(text: str) -> str:
    """D-112: Anthropic thinking 서명 흉내 — 텍스트 바이트에 묶인다. 다음 턴에 바이트가 바뀌어 돌아오면 맞지 않는다."""
    import hashlib
    return "sig-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def masked(text: object) -> bool:
    return isinstance(text, str) and bool(find_all(text)) and not any(m in text for m in RAW_MARKERS)
# 실제 AnythingLLM처럼 gzip 응답을 만든다 → 프록시의 content-encoding 처리 검증용
app.add_middleware(GZipMiddleware, minimum_size=100)


# D-086: 상류가 **실제로 받은** chat 본문. 응답은 게이트웨이가 복원하므로 응답만으로는
# "원문이 상류로 가지 않았다"를 증명할 수 없다. 이 기록이 그 증거다(테스트 전용 프로세스 메모리).
# D-118: 테스트는 이 앱 하나를 스택마다 다른 포트에 띄운다(같은 프로세스) — 기록은 서버 포트별이다.
RECEIVED: defaultdict[int, list[str]] = defaultdict(list)
# D-109: 상류에 닿은 모든 요청의 (메서드, 경로). 허용 목록 밖의 경로가 상류에 연결되지 않았다는 증거다.
HITS: defaultdict[int, list[list[str]]] = defaultdict(list)


def _port(request: Request) -> int:
    return request.scope["server"][1]


@app.middleware("http")
async def record_hits(request: Request, call_next):
    if not request.url.path.startswith("/__stub/"):
        HITS[_port(request)].append([request.method, request.url.path])
    if DELAY and request.method == "POST":
        await asyncio.sleep(DELAY)
    return await call_next(request)


@app.get("/")
async def root():
    return {"ok": True}


@app.get("/__stub/received")
async def received(request: Request):
    return {"bodies": RECEIVED[_port(request)]}


@app.get("/__stub/hits")
async def hits(request: Request):
    return {"hits": HITS[_port(request)]}


@app.get("/v1/models")
async def models(request: Request):
    """D-109: 받은 헤더를 그대로 돌려주고, 클라이언트에 넘어가면 안 되는 응답 헤더를 단다."""
    return JSONResponse({"object": "list", "data": [{"id": "stub-model", "object": "model"}],
                         "gateway_test": {"headers": dict(request.headers)}},
                        headers={"openai-organization": "org-stub", "x-request-id": "req_stub_models",
                                 "set-cookie": "__cf_bm=stub; Path=/", "openai-processing-ms": "3"})


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"] for part in content
            if isinstance(part, dict) and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return ""


@app.post("/v1/chat/completions")
async def openai_chat(request: Request):
    """OpenAI 호환 입구의 테스트 타겟. 모델을 흉내낼 뿐 공격 시나리오는 만들지 않는다.
    model 이름으로 상류 오류를 흉내낸다: stub-401 / stub-429 / stub-slow(2초 지연)."""
    RECEIVED[_port(request)].append((await request.body()).decode("utf-8", errors="replace"))
    payload = await request.json()
    model = payload.get("model") if isinstance(payload, dict) else None
    if model == "stub-401":
        return JSONResponse(status_code=401, content={"error": {
            "message": "Incorrect API key provided", "type": "invalid_request_error",
            "param": None, "code": "invalid_api_key"}})
    if model == "stub-429":
        return JSONResponse(status_code=429, headers={
            "retry-after": "7", "x-ratelimit-remaining-requests": "0"}, content={"error": {
            "message": "Rate limit reached", "type": "requests", "param": None,
            "code": "rate_limit_exceeded"}})
    if model == "stub-slow":
        await asyncio.sleep(2)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    messages = messages if isinstance(messages, list) else []
    texts = [(m.get("role"), _message_text(m)) for m in messages if isinstance(m, dict)]
    user = next((text for role, text in reversed(texts) if role == "user"), "")
    if model == "stub-agent":                     # D-112 에이전트 루프: 도구 결과를 읽고 답한다
        user = next((text for role, text in reversed(texts) if role == "tool"), user)
    tool_args = [call["function"]["arguments"] for m in messages if isinstance(m, dict)
                 for call in (m.get("tool_calls") or []) if isinstance(call, dict)
                 and isinstance(call.get("function"), dict) and isinstance(call["function"].get("arguments"), str)]
    if isinstance(model, str) and model.startswith("stub-stream"):
        # D-106: 마지막 user 문장을 N자씩 SSE 조각으로 보낸다(기본 3, `stub-stream-5`처럼 바꾼다). 3자 조각이면
        # 13자 대체값 `010-8419-3027`은 반드시 조각 경계에 걸린다. 실제 상류처럼 주석 줄·역할 조각·finish 조각·[DONE]을 낸다.
        # `stub-stream-tool`(D-107 B4): content 조각과 도구 호출 인자 조각을 번갈아 보낸다 — 두 채널이 섞인 모양.
        tool = model == "stub-stream-tool"
        size = int(model[len("stub-stream-"):]) if model.startswith("stub-stream-") and not tool else 3
        text = f"[stub] {user}"
        args = json.dumps({"to": user, "note": f"메모 {user}"}, ensure_ascii=False)

        def chunk(delta: dict, finish: str | None = None) -> str:
            return "data: " + json.dumps({
                "id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]},
                ensure_ascii=False, separators=(",", ":")) + "\n\n"      # 실제 OpenAI처럼 빈칸 없는 JSON — 재직렬화하면 바이트가 달라진다

        async def events():
            yield ": stub stream\n\n"
            yield chunk({"role": "assistant", "content": ""})
            if tool:
                yield chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                             "function": {"name": "send_sms", "arguments": ""}}]})
            for i in range(0, max(len(text), len(args)), size):
                if i < len(text):
                    yield chunk({"content": text[i:i + size]})
                if tool and i < len(args):
                    yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[i:i + size]}}]})
                await asyncio.sleep(CHUNK)          # 조각마다 전송 기회를 준다 — 한 덩어리로 뭉치지 않게
            yield chunk({}, "tool_calls" if tool else "stop")
            if isinstance(payload.get("stream_options"), dict) and payload["stream_options"].get("include_usage") is True:
                # D-120: OpenAI처럼 usage만 담은 마지막 조각(choices는 빈 배열)
                yield "data: " + json.dumps({"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": model,
                                             "choices": [], "usage": CHAT_USAGE}, separators=(",", ":")) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")
    if model == "stub-toolcall":
        # D-102: 마지막 user 문장을 도구 호출 인자에 실어 돌려준다 — 모델이 값을 인자로 옮겨 적는 흔한 모양.
        return {
            "id": "chatcmpl-stub", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {
                    "name": "send_sms", "arguments": json.dumps({"to": user}, ensure_ascii=False)}}]}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "gateway_test": {"tool_args_masked_seen": any(masked(a) for a in tool_args),
                             "tool_args_raw_phone_seen": any("010-2345-6789" in a for a in tool_args)},
        }
    answer = f"[stub] {user}"
    if model == "stub-last4":                     # D-113: 받은 번호의 끝 4자리만 말한다(복원되지 않는 조각)
        phones = [user[f.start:f.end] for f in find_all(user) if f.kind == "phone"]
        answer = "[stub] 끝자리 " + ("".join(c for c in phones[0] if c.isdigit())[-4:] if phones else "없음") + " 번호로 연락하세요"
    elif model == "stub-quiet":                   # 값을 되풀이하지 않는 정상 답
        answer = "[stub] 확인했습니다"
    body = {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": 0,
        "model": payload.get("model", "stub"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop",
        }],
        "usage": CHAT_USAGE,
        "gateway_test": {
            "user_masked_seen": any(role == "user" and masked(text) for role, text in texts),
            "system_raw_seen": any(role == "system" and "system@example.com" in text
                                   for role, text in texts),
            "tool_raw_seen": any(role == "tool" and "rag@example.com" in text
                                 for role, text in texts),
            "auth": request.headers.get("authorization"),
            "path": request.url.path,
            "query": request.url.query,
            "accept_encoding": request.headers.get("accept-encoding"),
            "tool_args_masked_seen": any(masked(a) for a in tool_args),
            "tool_args_raw_phone_seen": any("010-2345-6789" in a for a in tool_args),
        },
    }
    if model == "stub-html":                      # D-113: `<`·`>`를 \u003c·\u003e로 쓰는 직렬화(Go encoding/json 등)
        return Response(json.dumps(body, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e"),
                        media_type="application/json")
    return body


# ======================================================================================
# D-107 C: Anthropic Messages API 스텁 — /v1/messages
# ======================================================================================

def _sse(event: str, obj: dict) -> str:
    return f"event: {event}\ndata: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _anthropic_texts(messages: list) -> tuple[str, list[str], list[str], list[str]]:
    """(마지막 user 텍스트, user 텍스트들, tool_result 텍스트들, tool_use input 문자열들)."""
    users, tools, tool_inputs, last = [], [], [], ""
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        texts = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    texts.append(b["text"])
                elif b.get("type") == "tool_result":
                    inner = b.get("content")
                    if isinstance(inner, str):
                        tools.append(inner)
                    elif isinstance(inner, list):
                        tools.extend(ib["text"] for ib in inner if isinstance(ib, dict) and isinstance(ib.get("text"), str))
                elif b.get("type") == "tool_use":
                    tool_inputs.append(json.dumps(b.get("input"), ensure_ascii=False))
        if m.get("role") == "user":
            users.extend(texts)
            if texts:
                last = texts[-1]
    return last, users, tools, tool_inputs


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    RECEIVED[_port(request)].append((await request.body()).decode("utf-8", errors="replace"))
    payload = await request.json()
    model = payload.get("model") if isinstance(payload, dict) else None
    if model == "stub-401":
        return JSONResponse(status_code=401, content={"type": "error", "error": {
            "type": "authentication_error", "message": "invalid x-api-key"}})
    last, users, tools, tool_inputs = _anthropic_texts(payload.get("messages"))
    system = payload.get("system")
    system_text = system if isinstance(system, str) else " ".join(
        b.get("text", "") for b in system if isinstance(b, dict)) if isinstance(system, list) else ""
    text = f"[stub] {last}"
    gateway_test = {
        "user_masked_seen": any(masked(t) for t in users),
        "system_raw_seen": "system@example.com" in system_text,
        "tool_result_raw_seen": any("rag@example.com" in t for t in tools),
        "tool_result_masked_seen": any(masked(t) for t in tools),
        "tool_input_masked_seen": any(masked(t) for t in tool_inputs),
        "auth": request.headers.get("x-api-key"),
        "bearer": request.headers.get("authorization"),
        "version": request.headers.get("anthropic-version"),
    }
    history_thinking = [b for m in payload.get("messages", []) if isinstance(m, dict) and m.get("role") == "assistant"
                        and isinstance(m.get("content"), list) for b in m["content"] if isinstance(b, dict) and b.get("type") == "thinking"]
    gateway_test["thinking_ok"] = all(b.get("signature") == thinking_sig(b.get("thinking", "")) for b in history_thinking)
    gateway_test["thinking_seen"] = len(history_thinking)
    gateway_test["thinking_raw_seen"] = any(m in b.get("thinking", "") for b in history_thinking for m in RAW_MARKERS)
    thinking = f"사용자가 준 값을 확인한다: {last}" if isinstance(model, str) and model.endswith("thinking") else None
    tool = model == "stub-tool" or model == "stub-stream-tool"
    args = {"to": last, "note": f"메모 {last}"}
    if isinstance(model, str) and model.startswith("stub-stream"):
        size = 3

        async def events():
            yield _sse("message_start", {"type": "message_start", "message": {
                "id": "msg_stub", "type": "message", "role": "assistant", "model": model, "content": [],
                "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 0, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 4}}})
            t0 = 0
            if thinking is not None:                    # D-112: thinking 델타와 서명 델타
                t0 = 1
                yield _sse("content_block_start", {"type": "content_block_start", "index": 0,
                                                   "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
                for i in range(0, len(thinking), size):
                    yield _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                       "delta": {"type": "thinking_delta", "thinking": thinking[i:i + size]}})
                yield _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                   "delta": {"type": "signature_delta", "signature": thinking_sig(thinking)}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield _sse("content_block_start", {"type": "content_block_start", "index": t0, "content_block": {"type": "text", "text": ""}})
            yield _sse("ping", {"type": "ping"})
            for i in range(0, len(text), size):
                yield _sse("content_block_delta", {"type": "content_block_delta", "index": t0,
                                                   "delta": {"type": "text_delta", "text": text[i:i + size]}})
                await asyncio.sleep(CHUNK)
            if model == "stub-stream-error":            # D-124: 조각 몇 개 뒤 공급자 과부하 — 머리(200)는 이미 나갔으므로 오류 이벤트로 끝난다
                yield _sse("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
                return
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": t0})
            if tool:
                yield _sse("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
                    "type": "tool_use", "id": "toolu_1", "name": "send_sms", "input": {}}})
                partial = json.dumps(args, ensure_ascii=False)
                for i in range(0, len(partial), size):
                    yield _sse("content_block_delta", {"type": "content_block_delta", "index": 1,
                                                       "delta": {"type": "input_json_delta", "partial_json": partial[i:i + size]}})
                    await asyncio.sleep(CHUNK)
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": 1})
            yield _sse("message_delta", {"type": "message_delta", "delta": {
                "stop_reason": "tool_use" if tool else "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 9}})
            yield _sse("message_stop", {"type": "message_stop"})
        return StreamingResponse(events(), media_type="text/event-stream")
    content = [{"type": "text", "text": text}]
    if thinking is not None:
        content.insert(0, {"type": "thinking", "thinking": thinking, "signature": thinking_sig(thinking)})
    if tool:
        content.append({"type": "tool_use", "id": "toolu_1", "name": "send_sms", "input": args})
    return {"id": "msg_stub", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": "tool_use" if tool else "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 9}, "gateway_test": gateway_test}


# ======================================================================================
# D-107 C: OpenAI Responses API 스텁 — /v1/responses
# ======================================================================================

def _responses_texts(inp: object) -> tuple[str, list[str], list[str]]:
    """(마지막 user 텍스트, user 텍스트들, function_call_output 텍스트들)."""
    if isinstance(inp, str):
        return inp, [inp], []
    users, outputs, last = [], [], ""
    for item in inp if isinstance(inp, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call_output":
            out = item.get("output")
            if isinstance(out, str):
                outputs.append(out)
            continue
        content = item.get("content")
        texts = [content] if isinstance(content, str) else [
            p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)] if isinstance(content, list) else []
        if item.get("role") == "user":
            users.extend(texts)
            if texts:
                last = texts[-1]
    return last, users, outputs


@app.post("/v1/responses")
async def openai_responses(request: Request):
    RECEIVED[_port(request)].append((await request.body()).decode("utf-8", errors="replace"))
    payload = await request.json()
    model = payload.get("model") if isinstance(payload, dict) else None
    if model == "stub-401":
        return JSONResponse(status_code=401, content={"error": {
            "message": "Incorrect API key provided", "type": "invalid_request_error", "param": None, "code": "invalid_api_key"}})
    last, users, outputs = _responses_texts(payload.get("input"))
    text = f"[stub] {last}"
    tool = model in ("stub-tool", "stub-stream-tool")
    args = json.dumps({"to": last, "note": f"메모 {last}"}, ensure_ascii=False)
    gateway_test = {
        "user_masked_seen": any(masked(t) for t in users),
        "instructions_raw_seen": "system@example.com" in str(payload.get("instructions") or ""),
        "output_raw_seen": any("rag@example.com" in t for t in outputs),
        "output_masked_seen": any(masked(t) for t in outputs),
        "auth": request.headers.get("authorization"),
    }
    message = {"type": "message", "id": "msg_stub", "status": "completed", "role": "assistant",
               "content": [{"type": "output_text", "text": text, "annotations": []}]}
    call = {"type": "function_call", "id": "fc_stub", "call_id": "call_1", "name": "send_sms", "arguments": args, "status": "completed"}
    output = [message] + ([call] if tool else [])
    if isinstance(model, str) and model.endswith("reasoning"):      # D-112: 요약에 상류가 본 값(대체값)이 그대로 있어야 한다
        output.insert(0, {"type": "reasoning", "id": "rs_stub", "summary": [{"type": "summary_text", "text": f"요약: {last}"}]})
    response = {"id": "resp_stub", "object": "response", "created_at": 0, "status": "completed", "error": None,
                "incomplete_details": None, "model": model, "output": output,
                "usage": {"input_tokens": 1, "output_tokens": 9, "total_tokens": 10}, "gateway_test": gateway_test}
    if isinstance(model, str) and model.startswith("stub-stream"):
        size, seq = 3, iter(range(1000))

        def ev(kind: str, **fields: object) -> str:
            return _sse(kind, {"type": kind, "sequence_number": next(seq), **fields})

        async def events():
            yield ev("response.created", response={**response, "status": "in_progress", "output": []})
            yield ev("response.output_item.added", output_index=0, item={**message, "status": "in_progress", "content": []})
            yield ev("response.content_part.added", item_id="msg_stub", output_index=0, content_index=0,
                     part={"type": "output_text", "text": "", "annotations": []})
            if model != "stub-stream-done":             # D-124: stub-stream-done은 델타 없이 *.done·output_item.done·completed만 보낸다
                for i in range(0, len(text), size):
                    yield ev("response.output_text.delta", item_id="msg_stub", output_index=0, content_index=0, delta=text[i:i + size])
                    await asyncio.sleep(CHUNK)
            yield ev("response.output_text.done", item_id="msg_stub", output_index=0, content_index=0, text=text)
            yield ev("response.content_part.done", item_id="msg_stub", output_index=0, content_index=0, part=message["content"][0])
            yield ev("response.output_item.done", output_index=0, item=message)
            if tool:
                yield ev("response.output_item.added", output_index=1, item={**call, "arguments": "", "status": "in_progress"})
                for i in range(0, len(args), size):
                    yield ev("response.function_call_arguments.delta", item_id="fc_stub", output_index=1, delta=args[i:i + size])
                    await asyncio.sleep(CHUNK)
                yield ev("response.function_call_arguments.done", item_id="fc_stub", output_index=1, arguments=args)
                yield ev("response.output_item.done", output_index=1, item=call)
            yield ev("response.completed", response=response)
        return StreamingResponse(events(), media_type="text/event-stream")
    return response
