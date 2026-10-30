"""OpenAI Chat Completions 입구의 최소 계약."""
from __future__ import annotations

import json

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
VALID_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})
INJECTION_ROLES = frozenset({"user", "tool"})
# PII를 가리는 역할의 기본값(D-112). 어댑터가 developer·instructions를 system으로 정규화한다.
# assistant(D-099): 게이트웨이가 복원해 준 값이 다음 요청의 이력으로 돌아온다. tool·system(D-112, D-073을 뒤집음): 에이전트·RAG 앱의
# 개인정보는 대부분 도구 결과와 system 문서로 들어온다. 가짜 값이 결정적이라(D-111) 모델은 어디서나 같은 값을 보고 사용자는 원래 값을 돌려받는다.
PII_ROLES = frozenset({"user", "assistant", "tool", "system"})


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
        # 타입을 먼저 본다. role이 배열·객체면 `in frozenset`이 TypeError를 내 400 대신 500이 됐다.
        role = message.get("role") if isinstance(message, dict) else None
        if not isinstance(role, str) or role not in VALID_ROLES:
            raise ChatRequestError("each message must have a supported role", "messages")
        content = message.get("content")
        if content is None and message["role"] == "assistant":
            continue  # tool_calls를 담은 assistant 메시지는 content가 null일 수 있다.
        if isinstance(content, str):
            continue
        if not isinstance(content, list) or any(not _valid_part(part) for part in content):
            raise ChatRequestError("message content must be text or content parts", "messages")

    stream = payload.get("stream", False)
    if stream is None:
        stream = False   # OpenAI 스펙은 boolean | null — null은 "지정 안 함"이다(D-102)
    if not isinstance(stream, bool):
        raise ChatRequestError("stream must be a boolean", "stream", "invalid_stream")
    # true는 받아들인다 — 상류 SSE를 조각마다 흘려보내며 복원·감사·차단을 지킨다(D-106, gateway/streaming.py).
    return payload


def _valid_part(part: object) -> bool:
    if not isinstance(part, dict) or not isinstance(part.get("type"), str):
        return False
    return part.get("type") != "text" or isinstance(part.get("text"), str)
