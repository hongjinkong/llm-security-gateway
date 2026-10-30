"""API 어댑터(D-107 C) — Chat Completions·Anthropic Messages·Responses. 경로로 고른다."""
from __future__ import annotations

from gateway.api.anthropic import MessagesAdapter
from gateway.api.base import Adapter, ApiError, Doc, TextRef
from gateway.api.chat import ChatAdapter
from gateway.api.responses import ResponsesAdapter

ADAPTERS: dict[str, Adapter] = {a.path: a for a in (ChatAdapter(), MessagesAdapter(), ResponsesAdapter())}


def adapter_for(path: str) -> Adapter | None:
    return ADAPTERS.get(path)


def error_format_for(path: str) -> Adapter:
    """오류 본문 형식을 고를 때 쓴다 — 파싱 전(401·413)에도 경로로 안다. 모르는 경로는 OpenAI 형식."""
    return ADAPTERS["/v1/messages"] if path.startswith("/v1/messages") else ADAPTERS["/v1/chat/completions"]


__all__ = ["ADAPTERS", "Adapter", "ApiError", "Doc", "TextRef", "adapter_for", "error_format_for"]
