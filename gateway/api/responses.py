"""OpenAI Responses API 어댑터(D-107 C) — `/v1/responses`.

요청: `instructions`는 그대로(system). `input`은 문자열(user 한 턴) 또는 항목 목록 —
  {role, content: str | [{type: input_text|output_text|text, text}]}(type: message 포함) → 역할대로,
  {type: function_call, arguments} → assistant(도구 인자), {type: function_call_output, output: str|[...]} → tool.
  reasoning 항목(encrypted_content)은 손대지 않는다. `previous_response_id`로 상류에 쌓인 이전 턴은 게이트웨이가 볼 수 없다(이미 대체값으로 보냈다).
응답: 비스트리밍은 JSON 텍스트 전체 복원(output_text·function_call.arguments). 스트리밍은 (output_index, content_index)가 채널이고,
  전체 텍스트를 담은 이벤트(`*.done`·`response.completed`·`response.incomplete`)는 JSON 텍스트 전체를 복원한다.
차단: `status: "incomplete"`·`incomplete_details.reason: "content_filter"` + `gateway_blocked`. 오류: OpenAI 형식.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from fastapi.responses import JSONResponse, Response

from gateway.api.base import Adapter, ApiError, Doc, TextRef, now, sse, str_ref, stream_response
from gateway.api.chat import openai_error

PATH = "/v1/responses"
TEXT_PARTS = {"input_text", "output_text", "text"}
FULL_TEXT_EVENTS = {"response.output_text.done", "response.function_call_arguments.done", "response.content_part.done",
                    "response.output_item.done", "response.completed", "response.incomplete", "response.failed",
                    "response.refusal.done"}


class ResponsesAdapter(Adapter):
    name = "responses"
    path = PATH

    def parse(self, body: bytes) -> dict:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ApiError("request body must be valid JSON", "body", "invalid_json") from exc
        if not isinstance(payload, dict):
            raise ApiError("request body must be an object", "body", "invalid_json")
        inp = payload.get("input")
        if not isinstance(inp, (str, list)):
            raise ApiError("input must be a string or an array of items", "input")
        for item in inp if isinstance(inp, list) else []:
            if not isinstance(item, dict):
                raise ApiError("each input item must be an object", "input")
            if "role" in item and not isinstance(item["role"], str):
                raise ApiError("item role must be a string", "input")
            content = item.get("content")
            if content is not None and not isinstance(content, (str, list)):
                raise ApiError("item content must be a string or a list of parts", "input")
        instructions = payload.get("instructions")
        if instructions is not None and not isinstance(instructions, str):
            raise ApiError("instructions must be a string", "instructions")
        stream = payload.get("stream", False)
        if stream is not None and not isinstance(stream, bool):
            raise ApiError("stream must be a boolean", "stream", "invalid_stream")
        return payload

    def texts(self, payload: dict, doc: Doc) -> list[TextRef]:
        refs: list[TextRef] = []
        if isinstance(payload.get("instructions"), str):
            refs.append(str_ref(payload, "instructions", "system", -1, False))
        inp = payload["input"]
        if isinstance(inp, str):
            refs.append(str_ref(payload, "input", "user", 0, True))
            return refs
        users = [i for i, item in enumerate(inp) if item.get("role") == "user"]
        start = users[-1] if users else 0
        for i, item in enumerate(inp):
            turn, t = i >= start, item.get("type")
            if t == "function_call" and isinstance(item.get("arguments"), str):
                refs.append(str_ref(item, "arguments", "assistant", i, turn))
            elif t == "function_call_output":
                out = item.get("output")
                if isinstance(out, str):
                    refs.append(str_ref(item, "output", "tool", i, turn))
                elif isinstance(out, list):
                    self._parts(out, "tool", i, turn, refs)
            elif isinstance(item.get("role"), str):
                role = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant"}.get(item["role"])
                if role is None:
                    continue
                content = item.get("content")
                if isinstance(content, str):
                    refs.append(str_ref(item, "content", role, i, turn))
                elif isinstance(content, list):
                    self._parts(content, role, i, turn, refs)
        return refs

    @staticmethod
    def _parts(parts: list, role: str, msg: int, turn: bool, refs: list[TextRef]) -> None:
        for part in parts:
            if isinstance(part, dict) and part.get("type") in TEXT_PARTS and isinstance(part.get("text"), str):
                refs.append(str_ref(part, "text", role, msg, turn))

    def error(self, status: int, message: str, type_: str, code: str, param: str | None = None) -> JSONResponse:
        return openai_error(status, message, type_, code, param)

    def blocked(self, payload: dict, request_id: str, message: str, stream: bool) -> Response:
        model = self.model(payload)
        item = {"type": "message", "id": f"msg_{request_id}", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": message, "annotations": []}]}
        resp = {"id": f"resp_{request_id}", "object": "response", "created_at": now(), "status": "incomplete",
                "incomplete_details": {"reason": "content_filter"}, "error": None, "model": model, "output": [item],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "gateway_blocked": True}
        if not stream:
            return JSONResponse(status_code=200, content=resp)
        seq = iter(range(100))
        def ev(kind: str, **fields: object) -> str:
            return sse(kind, {"type": kind, "sequence_number": next(seq), **fields})
        body = (ev("response.created", response={**resp, "status": "in_progress", "incomplete_details": None, "output": []})
                + ev("response.output_item.added", output_index=0, item={**item, "status": "in_progress", "content": []})
                + ev("response.content_part.added", item_id=item["id"], output_index=0, content_index=0,
                     part={"type": "output_text", "text": "", "annotations": []})
                + ev("response.output_text.delta", item_id=item["id"], output_index=0, content_index=0, delta=message)
                + ev("response.output_text.done", item_id=item["id"], output_index=0, content_index=0, text=message)
                + ev("response.content_part.done", item_id=item["id"], output_index=0, content_index=0, part=item["content"][0])
                + ev("response.output_item.done", output_index=0, item=item)
                + ev("response.incomplete", response=resp))
        return stream_response(body)

    def stream_shape(self) -> "ResponsesShape":
        return ResponsesShape()


class ResponsesShape:
    """채널 = `o{output_index}.c{content_index}`(텍스트)·`o{output_index}.args`(도구 인자). 합성 조각은 마지막 델타의 모양을 빌린다."""

    def __init__(self) -> None:
        self.last: dict[str, dict] = {}         # 채널 → 마지막 델타 이벤트(item_id 등 필드 복사용)

    @staticmethod
    def is_done(payload: str) -> bool:
        return payload.strip() == "[DONE]"

    @staticmethod
    def json_channel(channel: str) -> bool:
        return channel.endswith(".args")

    def deltas(self, obj: dict) -> list:
        t = obj.get("type")
        if t == "response.output_text.delta" and isinstance(obj.get("delta"), str):
            ch = f"o{obj.get('output_index', 0)}.c{obj.get('content_index', 0)}"
        elif t == "response.function_call_arguments.delta" and isinstance(obj.get("delta"), str):
            ch = f"o{obj.get('output_index', 0)}.args"
        else:
            return []
        self.last[ch] = obj
        return [(ch, lambda o=obj: o["delta"], lambda v, o=obj: o.__setitem__("delta", v))]

    def closes(self, obj: dict) -> Callable[[str], bool] | None:
        t = obj.get("type")
        if t == "response.output_text.done":
            ch = f"o{obj.get('output_index', 0)}.c{obj.get('content_index', 0)}"
            return lambda c: c == ch
        if t == "response.function_call_arguments.done":
            ch = f"o{obj.get('output_index', 0)}.args"
            return lambda c: c == ch
        if t in ("response.output_item.done", "response.completed", "response.incomplete", "response.failed"):
            if t == "response.output_item.done":
                prefix = f"o{obj.get('output_index', 0)}."
                return lambda c: c.startswith(prefix)
            return lambda c: True
        return None

    def inject(self, obj: dict, channel: str, text: str) -> bool:
        return False                             # done 이벤트는 전체 텍스트를 따로 담는다 — 꼬리는 앞에 델타로 합성한다

    def synthesize(self, channel: str, text: str) -> str:
        last = self.last.get(channel)
        if last is None:                         # 델타를 한 번도 못 본 채널은 없다(델타가 있어야 꼬리가 생긴다)
            return ""
        return sse(last.get("type"), {**last, "delta": text})

    @staticmethod
    def full_text(obj: dict) -> bool:
        return obj.get("type") in FULL_TEXT_EVENTS
