"""SSE 스트리밍 응답의 토큰 복원 — OpenAI `chat.completion.chunk` 조각의 `choices[0].delta.content`만 되돌린다(D-106).

바이트를 먹고 바이트를 낸다. 이 모듈은 볼트도 세션도 모른다 — 복원 함수 하나를 주입받는다
(`gateway/main.py`가 `pii_mask` 검사기의 볼트로 만든다).

하는 일은 둘이다.
  1. `data:` 줄의 JSON에서 `choices[0].delta.content`를 복원해 다시 직렬화한다. 내용이 바뀌지 않은 줄과
     그 밖의 모든 줄(빈 줄·`:` 주석·`event:`·usage 조각·`[DONE]`·JSON이 아닌 줄)은 바이트 그대로 지난다.
  2. 토큰 `[PII:kind:n]`이 두 조각에 걸릴 수 있으므로(`[PII:pho` / `ne:1]`), 조각 끝에서 토큰의 앞부분일 수 있는
     꼬리를 보류했다가 다음 조각 앞에 붙인다. 보류 꼬리는 finish 조각에서 비우고, finish 조각 없이 스트림이
     끝나면 content만 담은 조각 하나를 합성해 `[DONE]` 앞에 내보낸다. 조각을 버리거나 순서를 바꾸지 않는다.

복원하지 않는 것: `tool_calls[].function.arguments` 조각, `choices[1..]`(n>1). 그런 토큰은 출력 전체의
잔여 토큰 수(`out_text`)로 감사에 남는다.
"""
from __future__ import annotations

import codecs
import json
import re
from collections.abc import Callable

# 조각 끝이 토큰의 앞부분일 수 있는 꼴 — `[`, `[P`, `[PII:`, `[PII:phone`, `[PII:phone:12`(닫는 대괄호가 아직 안 옴).
# 대괄호는 선택이다: 모델이 `[`를 떨어뜨린 토큰도 vault.TOKEN_RE가 받으므로 `P`·`PII:phone:1`도 보류한다.
# 모두 선택 요소라 빈 문자열에도 맞는다 — 호출 쪽은 match 길이 0을 "보류 없음"으로 본다.
TAIL_RE = re.compile(r"\[?(?:P(?:I(?:I(?::(?:[a-z]+(?::\d*)?)?)?)?)?)?$")
# 보류 상한. `[PII:secret:` 12자 + 번호. 이보다 길면 토큰이 아니다 — 끝없이 이어지는 숫자를 영원히 붙들지 않는다.
MAX_HOLD = 32
DATA_RE = re.compile(r"data: ?")


class StreamRestorer:
    """`feed(bytes) -> bytes`를 조각마다, `finish() -> bytes`를 스트림 끝에 한 번 부른다."""

    def __init__(self, restore: Callable[[str], tuple[str, int]]) -> None:
        self._restore = restore                 # 텍스트 → (복원된 텍스트, 복원 건수)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")   # 다중 바이트 글자가 조각에 걸려도 깨지지 않게
        self._line = ""                         # 아직 줄바꿈이 오지 않은 줄
        self._pending = ""                      # 토큰 조각일 수 있어 보류 중인 꼬리
        self._last: dict | None = None          # 마지막으로 본 조각 — 합성 조각의 id·model
        self._content_in: list[str] = []        # 상류가 보낸 content 원문(이어 붙이면 전체 텍스트 — 카나리 관측용)
        self._out: list[str] = []               # 내보낸 전부(잔여 토큰 검사용)
        self.restored = 0

    # --- 공개 --------------------------------------------------------------
    def feed(self, data: bytes) -> bytes:
        text = self._line + self._decoder.decode(data)
        lines = text.split("\n")
        self._line = lines.pop()                # 마지막 조각은 줄이 끝나지 않았을 수 있다
        return self._emit([self._handle(line, "\n") for line in lines])

    def finish(self) -> bytes:
        """스트림 끝. 줄바꿈 없이 끝난 마지막 줄을 처리하고, 보류 꼬리가 남았으면 합성 조각으로 내보낸다."""
        out = []
        tail = self._line + self._decoder.decode(b"", final=True)
        self._line = ""
        if tail:
            out.append(self._handle(tail, ""))
        if self._pending:
            out.append(self._synthesized("\n"))
        return self._emit(out)

    @property
    def content_in(self) -> str:
        return "".join(self._content_in)

    @property
    def out_text(self) -> str:
        return "".join(self._out)

    # --- 내부 --------------------------------------------------------------
    def _emit(self, parts: list[str]) -> bytes:
        self._out.extend(parts)
        return "".join(parts).encode("utf-8")

    def _handle(self, line: str, newline: str) -> str:
        """줄 하나(줄바꿈 제외) → 내보낼 텍스트(줄바꿈 포함). `\\r`은 줄의 일부로 보존한다."""
        body = line.rstrip("\r")
        ending = line[len(body):] + newline
        m = DATA_RE.match(body)
        if not m:
            return line + newline                           # 빈 줄·주석·event: — 그대로
        payload = body[m.end():]
        if payload.strip() == "[DONE]":
            prefix = self._synthesized(ending) if self._pending else ""
            return prefix + line + newline
        try:
            obj = json.loads(payload)
        except ValueError:
            return line + newline
        if not isinstance(obj, dict) or not self._restore_chunk(obj):
            return line + newline                           # 내용이 바뀌지 않았으면 재직렬화하지 않는다
        return body[:m.end()] + json.dumps(obj, ensure_ascii=False) + ending

    def _restore_chunk(self, obj: dict) -> bool:
        """choices[0].delta.content를 제자리에서 복원한다. 바뀌었으면 True."""
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return False
        choice = choices[0]
        if choice.get("index", 0) != 0:
            return False
        self._last = obj
        delta = choice.get("delta")
        content = delta.get("content") if isinstance(delta, dict) else None
        finished = choice.get("finish_reason") is not None
        if not isinstance(content, str):
            if not (finished and self._pending):
                return False
            content = ""
        self._content_in.append(content)
        text = self._pending + content
        if finished:
            emit, self._pending = text, ""                  # finish 조각: 보류 꼬리를 전부 비운다
        else:
            emit, self._pending = self._split(text)
        restored, n = self._restore(emit)
        self.restored += n
        if restored == content:
            return False
        if not isinstance(delta, dict):
            delta = choice["delta"] = {}
        delta["content"] = restored
        return True

    @staticmethod
    def _split(text: str) -> tuple[str, str]:
        """(지금 내보낼 앞부분, 보류할 꼬리). 꼬리는 토큰의 앞부분일 수 있는 가장 긴 접미사다."""
        m = TAIL_RE.search(text)
        tail = m.group(0) if m else ""
        if not tail or len(tail) > MAX_HOLD:
            return text, ""
        return text[:m.start()], tail

    def _synthesized(self, ending: str) -> str:
        """finish 조각 없이 스트림이 끝났다. 보류 꼬리를 content만 담은 조각 하나로 내보낸다."""
        last = self._last or {}
        restored, n = self._restore(self._pending)
        self.restored += n
        self._pending = ""
        obj = {**{k: last[k] for k in ("id", "created", "model", "system_fingerprint") if k in last},
               "object": "chat.completion.chunk",
               "choices": [{"index": 0, "delta": {"content": restored}, "finish_reason": None}]}
        return "data: " + json.dumps(obj, ensure_ascii=False) + ending + ending
