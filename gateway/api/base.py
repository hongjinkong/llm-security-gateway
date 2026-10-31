"""어댑터 계약(D-107 C).

어댑터는 API 하나의 **모양**을 안다 — 파싱(요청당 1회), 텍스트 참조(역할·이번 턴·메시지 번호), 직렬화(바뀌었을 때 1회),
오류 형식, 차단 응답, 스트림 모양. 검사기는 어댑터가 주는 `TextRef`만 보고 제자리에서 바꾼다. 검사기가 API를 모르게 하는 자리다.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import JSONResponse, Response


@dataclass(frozen=True)
class TextRef:
    """검사할 수 있는 텍스트 하나. role은 system·user·assistant·tool 중 하나로 정규화돼 있다."""

    role: str
    msg: int                          # 메시지 번호(같은 메시지의 파트는 같은 번호) — 이력 가림은 메시지 단위다
    turn: bool                        # 이번 턴(마지막 user 메시지부터 끝까지)인가
    get: Callable[[], str]
    put: Callable[[str], None]


class ApiError(ValueError):
    def __init__(self, message: str, param: str | None = None, code: str = "invalid_request",
                 status: int = 400, type_: str = "invalid_request_error") -> None:
        super().__init__(message)
        self.param, self.code, self.status, self.type_ = param, code, status, type_


@dataclass
class Doc:
    """파싱된 요청 본문. 검사기가 텍스트를 바꾸면 dirty가 되고, 체인이 끝에서 한 번 직렬화한다."""

    adapter: "Adapter"
    payload: dict
    dirty: bool = False
    _refs: list[TextRef] | None = field(default=None, repr=False)

    def texts(self) -> list[TextRef]:
        if self._refs is None:
            self._refs = self.adapter.texts(self.payload, self)
        return self._refs

    def serialize(self) -> bytes:
        """바뀐 본문의 바이트. 검사기가 TRANSFORM을 돌려주기 직전에 부른다 — dirty를 내린다."""
        self.dirty = False
        return self.adapter.serialize(self.payload)

    def put(self, ref: TextRef, text: str) -> None:
        if text != ref.get():
            ref.put(text)
            self.dirty = True


class Adapter:
    name = "base"
    path = ""

    # --- 요청 ---------------------------------------------------------------
    def parse(self, body: bytes) -> dict:
        raise NotImplementedError

    def texts(self, payload: dict, doc: Doc) -> list[TextRef]:
        raise NotImplementedError

    def serialize(self, payload: dict) -> bytes:
        import json
        try:
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:      # 짝 없는 서로게이트(D-124) — UTF-8로 못 쓴다. JSON 이스케이프(\ud800)로 쓰면 클라이언트가 보낸 뜻 그대로다
            return json.dumps(payload).encode("ascii")

    def wants_stream(self, payload: dict) -> bool:
        return payload.get("stream") is True

    def model(self, payload: dict) -> str:
        """클라이언트가 보낸 model. 짝 없는 서로게이트(JSON `"\\ud800"`)는 '?'로 바꾼다(D-124) — 그대로 두면 감사 줄·차단 응답·stats가
        UTF-8로 못 바꿔 실패한다(감사 줄이 사라지고 stats가 500). 상류로 가는 본문은 그대로다."""
        m = payload.get("model")
        return m.encode("utf-8", "replace").decode() if isinstance(m, str) else "gateway"

    def upstream_path(self) -> str:
        return self.path

    def with_stream_usage(self, body: bytes) -> tuple[bytes, bool]:
        """스트리밍 상류 요청을 usage를 받도록 손질한다(D-120). (본문, 클라이언트 스트림에서 usage 조각을 뺄지). 기본은 그대로 — 스트림이 usage를 준다."""
        return body, False

    def usage_raw(self, obj: dict) -> Any:
        """응답 객체나 스트림 이벤트에 실린 공급자 usage(D-120). 없으면 None."""
        return obj.get("usage")

    def usage(self, raw: Any) -> dict | None:
        return normalize_usage(raw, self.name)

    # --- 응답 ---------------------------------------------------------------
    def error(self, status: int, message: str, type_: str, code: str, param: str | None = None) -> JSONResponse:
        raise NotImplementedError

    def blocked(self, payload: dict, request_id: str, message: str, stream: bool) -> Response:
        raise NotImplementedError

    def stream_shape(self) -> Any:
        raise NotImplementedError


def now() -> int:
    return int(time.time())


def _tokens(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def normalize_usage(u: object, api: str) -> dict | None:
    """공급자 usage → 감사 줄의 `{"input", "output", "cache_read", "cache_write"}`(D-120). 주지 않은 항목은 0."""
    if not isinstance(u, dict):
        return None
    if api == "messages":
        return {"input": _tokens(u.get("input_tokens")), "output": _tokens(u.get("output_tokens")),
                "cache_read": _tokens(u.get("cache_read_input_tokens")), "cache_write": _tokens(u.get("cache_creation_input_tokens"))}
    chat = api == "chat"
    details = u.get("prompt_tokens_details" if chat else "input_tokens_details")
    return {"input": _tokens(u.get("prompt_tokens" if chat else "input_tokens")),
            "output": _tokens(u.get("completion_tokens" if chat else "output_tokens")),
            "cache_read": _tokens(details.get("cached_tokens")) if isinstance(details, dict) else 0, "cache_write": 0}


def sse(event: str | None, obj: dict) -> str:
    import json
    head = f"event: {event}\n" if event else ""
    return head + "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_response(body: str) -> Response:
    return Response(content=body, status_code=200, media_type="text/event-stream", headers={"cache-control": "no-cache"})


# --- 텍스트 참조 도구 ---------------------------------------------------------

def str_ref(container: dict | list, key: Any, role: str, msg: int, turn: bool) -> TextRef:
    return TextRef(role, msg, turn, lambda: container[key], lambda v: container.__setitem__(key, v))


def walk_strings(obj: Any, role: str, msg: int, turn: bool, out: list[TextRef]) -> None:
    """객체 안의 모든 문자열 값(도구 호출 input 같은 임의 JSON)을 참조로 모은다. 키는 바꾸지 않는다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                out.append(str_ref(obj, k, role, msg, turn))
            else:
                walk_strings(v, role, msg, turn, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                out.append(str_ref(obj, i, role, msg, turn))
            else:
                walk_strings(v, role, msg, turn, out)
