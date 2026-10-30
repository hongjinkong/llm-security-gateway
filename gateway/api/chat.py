"""OpenAI Chat Completions 어댑터(D-107 C). 파서는 openai_api.py의 것을 그대로 쓴다(D-074·D-102)."""
from __future__ import annotations

import os

from fastapi.responses import JSONResponse, Response

from gateway.api.base import Adapter, ApiError, Doc, TextRef, now, sse, str_ref, stream_response
from gateway.openai_api import CHAT_COMPLETIONS_PATH, ChatRequestError, parse_chat_request
from gateway.streaming import ChatShape

ROLES = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant", "tool": "tool"}


def openai_error(status: int, message: str, type_: str, code: str, param: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "message": message, "type": type_, "param": param, "code": code}})


class ChatAdapter(Adapter):
    name = "chat"
    path = CHAT_COMPLETIONS_PATH

    def parse(self, body: bytes) -> dict:
        try:
            return parse_chat_request(body)
        except ChatRequestError as exc:
            raise ApiError(str(exc), exc.param, exc.code) from exc

    def texts(self, payload: dict, doc: Doc) -> list[TextRef]:
        messages = payload["messages"]
        users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        start = users[-1] if users else 0
        refs: list[TextRef] = []
        for i, m in enumerate(messages):
            role, turn = ROLES[m["role"]], i >= start
            content = m.get("content")
            if isinstance(content, str):
                refs.append(str_ref(m, "content", role, i, turn))
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                        refs.append(str_ref(part, "text", role, i, turn))
            calls = m.get("tool_calls")
            for call in calls if isinstance(calls, list) else []:     # 도구 호출 인자(D-102 #3)
                fn = call.get("function") if isinstance(call, dict) else None
                if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                    refs.append(str_ref(fn, "arguments", role, i, turn))
        return refs

    def upstream_path(self) -> str:
        # D-086: Gemini의 OpenAI 호환 입구는 /v1beta/openai/chat/completions라 chat completions만 상류 경로를 바꿀 수 있다.
        return os.environ.get("GATEWAY_CHAT_UPSTREAM_PATH", CHAT_COMPLETIONS_PATH)

    def error(self, status: int, message: str, type_: str, code: str, param: str | None = None) -> JSONResponse:
        return openai_error(status, message, type_, code, param)

    def blocked(self, payload: dict, request_id: str, message: str, stream: bool) -> Response:
        model = self.model(payload)
        if stream:
            chunk = {"id": f"chatcmpl-{request_id}", "object": "chat.completion.chunk", "created": now(), "model": model,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": message},
                                  "finish_reason": "content_filter"}], "gateway_blocked": True}
            return stream_response(sse(None, chunk) + "data: [DONE]\n\n")
        return JSONResponse(status_code=200, content={
            "id": f"chatcmpl-{request_id}", "object": "chat.completion", "created": now(), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": message}, "finish_reason": "content_filter"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "gateway_blocked": True})

    def stream_shape(self) -> ChatShape:
        return ChatShape()
