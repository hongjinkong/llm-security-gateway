"""Anthropic Messages API 어댑터(D-107 C) — `/v1/messages`.

요청: `system`(문자열 또는 text 블록 목록) → system, `messages[].content`는 문자열 또는 블록 목록. 텍스트 document 블록 → system(D-112).
  text 블록 → 메시지 역할(user·assistant), tool_result 블록(user 메시지 안) → tool, tool_use.input의 문자열 값 → assistant(도구 인자).
  image·thinking·redacted_thinking 블록은 손대지 않는다(thinking의 signature는 바꾸면 상류가 거부한다).
응답: 비스트리밍은 문자열 값마다 복원하되 thinking 블록은 건너뛴다(D-112). 스트리밍은 content block index가 채널이다.
차단: `stop_reason: "refusal"`(Anthropic의 거부 종료 사유) + `gateway_blocked`. 오류: `{"type":"error","error":{"type","message"}}`.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse, Response

from gateway.api.base import Adapter, ApiError, Doc, TextRef, sse, str_ref, stream_response, walk_strings
from gateway.streaming import ref

PATH = "/v1/messages"
ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 413: "invalid_request_error",
               429: "rate_limit_error", 500: "api_error", 502: "api_error", 504: "api_error"}


def anthropic_error(status: int, message: str, type_: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "type": "error", "error": {"type": type_ or ERROR_TYPES.get(status, "api_error"), "message": message}})


class MessagesAdapter(Adapter):
    name = "messages"
    path = PATH

    def parse(self, body: bytes) -> dict:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ApiError("request body must be valid JSON", "body", "invalid_json") from exc
        if not isinstance(payload, dict):
            raise ApiError("request body must be an object", "body", "invalid_json")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ApiError("messages must be a non-empty array", "messages")
        for m in messages:
            role = m.get("role") if isinstance(m, dict) else None
            if role not in ("user", "assistant"):
                raise ApiError("each message must have role user or assistant", "messages")
            content = m.get("content")
            if isinstance(content, str):
                continue
            if not isinstance(content, list) or any(not isinstance(b, dict) or not isinstance(b.get("type"), str)
                                                    for b in content):
                raise ApiError("message content must be a string or a list of content blocks", "messages")
        system = payload.get("system")
        if system is not None and not isinstance(system, str) and not (
                isinstance(system, list) and all(isinstance(b, dict) for b in system)):
            raise ApiError("system must be a string or a list of text blocks", "system")
        stream = payload.get("stream", False)
        if stream is not None and not isinstance(stream, bool):
            raise ApiError("stream must be a boolean", "stream", "invalid_stream")
        return payload

    def texts(self, payload: dict, doc: Doc) -> list[TextRef]:
        refs: list[TextRef] = []
        system = payload.get("system")
        if isinstance(system, str):
            refs.append(str_ref(payload, "system", "system", -1, False))
        elif isinstance(system, list):
            for b in system:
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    refs.append(str_ref(b, "text", "system", -1, False))
        messages = payload["messages"]
        users = [i for i, m in enumerate(messages) if m["role"] == "user"]
        start = users[-1] if users else 0
        for i, m in enumerate(messages):
            role, turn, content = m["role"], i >= start, m.get("content")
            if isinstance(content, str):
                refs.append(str_ref(m, "content", role, i, turn))
                continue
            for b in content or []:
                t = b.get("type")
                if t == "text" and isinstance(b.get("text"), str):
                    refs.append(str_ref(b, "text", role, i, turn))
                elif t == "tool_result":                               # 도구 결과 = tool 역할(인젝션 검사 대상)
                    inner = b.get("content")
                    if isinstance(inner, str):
                        refs.append(str_ref(b, "content", "tool", i, turn))
                    elif isinstance(inner, list):
                        for ib in inner:
                            if isinstance(ib, dict) and ib.get("type") == "text" and isinstance(ib.get("text"), str):
                                refs.append(str_ref(ib, "text", "tool", i, turn))
                elif t == "tool_use" and isinstance(b.get("input"), (dict, list)):   # 도구 호출 인자 = assistant(마스킹 대상)
                    walk_strings(b["input"], "assistant", i, turn, refs)
                elif t == "document" and isinstance(b.get("source"), dict) and b["source"].get("type") == "text" \
                        and isinstance(b["source"].get("data"), str):                  # 텍스트 문서(RAG) = system 문서처럼(D-112)
                    refs.append(str_ref(b["source"], "data", "system", i, turn))
        return refs

    def error(self, status: int, message: str, type_: str, code: str, param: str | None = None) -> JSONResponse:
        return anthropic_error(status, message, ERROR_TYPES.get(status, type_))

    def blocked(self, payload: dict, request_id: str, message: str, stream: bool) -> Response:
        model = self.model(payload)
        msg = {"id": f"msg_{request_id}", "type": "message", "role": "assistant", "model": model,
               "content": [{"type": "text", "text": message}], "stop_reason": "refusal", "stop_sequence": None,
               "usage": {"input_tokens": 0, "output_tokens": 0}, "gateway_blocked": True}
        if not stream:
            return JSONResponse(status_code=200, content=msg)
        start = {**msg, "content": [], "stop_reason": None}
        body = (sse("message_start", {"type": "message_start", "message": start})
                + sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                + sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": message}})
                + sse("content_block_stop", {"type": "content_block_stop", "index": 0})
                + sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "refusal", "stop_sequence": None},
                                        "usage": {"output_tokens": 0}})
                + sse("message_stop", {"type": "message_stop"}))
        return stream_response(body)

    def usage_raw(self, obj: dict) -> Any:
        # 스트림은 message_start에 입력·캐시, message_delta에 출력(누적)을 싣는다 — 펌프가 둘을 덮어 합친다
        if obj.get("type") == "message_start" and isinstance(obj.get("message"), dict):
            return obj["message"].get("usage")
        return obj.get("usage")

    def stream_shape(self) -> "MessagesShape":
        return MessagesShape()


class MessagesShape:
    """채널 = content block index(`b{i}`). text_delta.text·input_json_delta.partial_json을 복원한다."""

    def __init__(self) -> None:
        self.kinds: dict[int, str] = {}         # index → text | tool_use | thinking…

    @staticmethod
    def is_done(payload: str) -> bool:
        return False

    def json_channel(self, channel: str) -> bool:
        return self.kinds.get(int(channel[1:])) == "tool_use"      # input_json_delta.partial_json

    def deltas(self, obj: dict) -> list:
        t = obj.get("type")
        if t == "content_block_start" and isinstance(obj.get("content_block"), dict):
            self.kinds[obj.get("index", 0)] = obj["content_block"].get("type", "")
            return []
        if t != "content_block_delta" or not isinstance(obj.get("delta"), dict):
            return []
        delta, idx = obj["delta"], obj.get("index", 0)
        key = {"text_delta": "text", "input_json_delta": "partial_json"}.get(delta.get("type"))
        if key and isinstance(delta.get(key), str):
            return [ref(f"b{idx}", delta, key)]
        return []

    def closes(self, obj: dict) -> Callable[[str], bool] | None:
        t = obj.get("type")
        if t == "content_block_stop":
            idx = f"b{obj.get('index', 0)}"
            return lambda ch: ch == idx
        if t in ("message_delta", "message_stop"):
            return lambda ch: True
        return None

    def inject(self, obj: dict, channel: str, text: str) -> bool:
        return False                             # stop 이벤트에는 텍스트 자리가 없다 — 앞에 합성한다

    def synthesize(self, channel: str, text: str) -> str:
        idx = int(channel[1:])
        kind = "input_json_delta" if self.kinds.get(idx) == "tool_use" else "text_delta"
        key = "partial_json" if kind == "input_json_delta" else "text"
        return sse("content_block_delta", {"type": "content_block_delta", "index": idx, "delta": {"type": kind, key: text}})

    @staticmethod
    def full_text(obj: dict) -> bool:
        return False
