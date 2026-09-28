"""OpenAI Chat Completions 입구의 최소 계약."""
from __future__ import annotations

import json
from collections.abc import Callable, Collection

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
VALID_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})
INJECTION_ROLES = frozenset({"user", "tool"})
PII_ROLES = frozenset({"user"})


class ChatRequestError(ValueError):
    def __init__(self, message: str, param: str, code: str = "invalid_messages") -> None:
        super().__init__(message)
        self.param = param
        self.code = code


def parse_chat_request(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ChatRequestError("request body must be valid JSON", "body", "invalid_json") from exc
    if not isinstance(payload, dict):
        raise ChatRequestError("request body must be an object", "body", "invalid_json")

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ChatRequestError("messages must be a non-empty array", "messages")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in VALID_ROLES:
            raise ChatRequestError("each message must have a supported role", "messages")
        content = message.get("content")
        if content is None and message["role"] == "assistant":
            continue  # tool_calls를 담은 assistant 메시지는 content가 null일 수 있다.
        if isinstance(content, str):
            continue
        if not isinstance(content, list) or any(not _valid_part(part) for part in content):
            raise ChatRequestError("message content must be text or content parts", "messages")

    stream = payload.get("stream", False)
    if not isinstance(stream, bool):
        raise ChatRequestError("stream must be a boolean", "stream", "invalid_stream")
    if stream:
        raise ChatRequestError("streaming is not supported", "stream", "unsupported_streaming")
    return payload


def _valid_part(part: object) -> bool:
    if not isinstance(part, dict) or not isinstance(part.get("type"), str):
        return False
    return part.get("type") != "text" or isinstance(part.get("text"), str)


def chat_texts(payload: dict, roles: Collection[str]) -> list[str]:
    texts: list[str] = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict) or message.get("role") not in roles:
            continue
        content = message.get("content")
        if isinstance(content, str):
            if content:
                texts.append(content)
        elif isinstance(content, list):
            texts.extend(part["text"] for part in content
                         if isinstance(part, dict) and part.get("type") == "text"
                         and isinstance(part.get("text"), str) and part["text"])
    return texts


def map_chat_texts(payload: dict, roles: Collection[str], transform: Callable[[str], str]) -> None:
    """선택한 역할의 텍스트만 제자리에서 바꾼다. 파싱 직후 객체에만 사용한다."""
    for message in payload["messages"]:
        if message["role"] not in roles:
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = transform(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    part["text"] = transform(part["text"])
