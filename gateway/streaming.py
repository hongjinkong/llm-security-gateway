"""SSE 스트리밍 응답의 대체값 복원 — 이벤트마다 텍스트를 나르는 **채널**을 찾아 제자리에서 되돌린다(D-106 → D-107 B·C).

바이트를 먹고 바이트를 낸다. 이 모듈은 볼트도 세션도 모른다 — 복원·보류 함수와 API별 **모양(shape)** 하나를 주입받는다.

하는 일은 셋이다.
  1. SSE 이벤트(빈 줄로 끝나는 블록) 단위로 자른다. `data:` 줄이 정확히 하나이고 JSON 객체면 모양에게 채널을 묻는다.
     그 밖의 블록(주석·`ping`·`[DONE]`·JSON이 아닌 것·data 줄이 여럿인 것)과 내용이 바뀌지 않은 블록은 바이트 그대로 지난다.
  2. 채널(Chat은 choice의 content와 tool index, Anthropic은 content block index, Responses는 output·content index)마다
     대체값이 두 조각에 걸릴 수 있으므로(`010-84` / `19-3027`) 조각 끝의 꼬리를 보류했다가 다음 조각 앞에 붙인다(`hold`).
     채널이 끝나는 이벤트(finish_reason·content_block_stop·*.done)에서 그 채널의 꼬리를 그 이벤트에 끼우거나(inject)
     그 이벤트 앞에 합성 조각으로 내보내고(synthesize), 끝 이벤트 없이 스트림이 끝나면 `[DONE]`·스트림 끝에서 합성한다.
  3. 전체 텍스트를 담은 이벤트(Responses의 `*.done`·`response.completed`)는 JSON 텍스트 전체를 복원한다(원문은 JSON 이스케이프).
조각을 버리거나 순서를 바꾸지 않는다.
"""
from __future__ import annotations

import codecs
import json
import re
from collections.abc import Callable
from typing import Any, Protocol

from gateway.vault import json_escape, map_strings

Ref = tuple[str, Callable[[], str | None], Callable[[str], None]]      # (채널, 읽기, 쓰기)


def ref(channel: str, obj: dict, key: str) -> Ref:
    """obj[key]를 읽고 쓰는 채널 참조."""
    return channel, lambda: obj[key], lambda v: obj.__setitem__(key, v)
BLOCK_END = re.compile(r"\r?\n\r?\n")
DATA_RE = re.compile(r"^data: ?", re.M)


class Shape(Protocol):
    """API별 스트림 모양. 인스턴스는 요청마다 하나다(이벤트 사이의 상태를 든다)."""

    def deltas(self, obj: dict) -> list[Ref]: ...                      # 이 이벤트가 나르는 텍스트 조각들
    def closes(self, obj: dict) -> Callable[[str], bool] | None: ...   # 이 이벤트에서 끝나는 채널의 판별식(없으면 None)
    def inject(self, obj: dict, channel: str, text: str) -> bool: ...  # 끝 이벤트의 필드 앞에 꼬리를 끼운다. 못 하면 False
    def synthesize(self, channel: str, text: str) -> str: ...          # 꼬리만 담은 이벤트 블록 전체(event 줄·빈 줄 포함)
    def full_text(self, obj: dict) -> bool: ...                        # 전체 텍스트를 담은 이벤트인가(JSON 텍스트 전체 복원)
    def is_done(self, payload: str) -> bool: ...                       # 스트림 종료 표시(`[DONE]`)인가
    def json_channel(self, channel: str) -> bool: ...                  # 그 채널이 JSON 텍스트(도구 인자)를 나르는가 — 복원 값을 이스케이프한다(D-113)


class StreamRestorer:
    """`feed(bytes) -> bytes`를 조각마다, `finish() -> bytes`를 스트림 끝에 한 번 부른다."""

    def __init__(self, shape: Shape, restore: Callable[..., tuple[str, int]],
                 hold: Callable[[str], int], usage: Callable[[dict], Any] | None = None,
                 drop: Callable[[dict], bool] | None = None) -> None:
        self._shape = shape
        self._restore = restore                 # (텍스트, escape=None) → (복원된 텍스트, 복원 건수)
        self._hold = hold                       # 텍스트 → 대체값의 앞부분일 수 있는 꼬리 길이
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""                          # 아직 블록이 끝나지 않은 텍스트
        self._pending: dict[str, str] = {}      # 채널 → 보류 중인 꼬리
        self._visible: list[str] = []          # 복원 대상 채널로 내보낸 텍스트(사고 과정 밖) — 감사의 잔여 대체값을 여기서 센다(D-112)
        self.restored = 0
        self.final_restored = 0                 # 응답 전체를 담은 끝 이벤트에서 복원한 수(D-124 — Responses completed·incomplete·failed)
        self.failed = False                     # 상류가 머리(200) 뒤 스트림 안에 오류 이벤트를 보냈다(D-124)
        self._usage, self._drop = usage, drop   # 이벤트의 usage 읽기, 내보내지 않을 이벤트(D-120 — Chat의 usage 조각)
        self.usage_raw: dict = {}               # 이벤트들의 usage를 차례로 덮어 합친 것(Messages: message_start + message_delta)

    # --- 공개 --------------------------------------------------------------
    def feed(self, data: bytes) -> bytes:
        self._buf += self._decoder.decode(data)
        parts: list[str] = []
        while True:
            m = BLOCK_END.search(self._buf)
            if not m:
                break
            block, self._buf = self._buf[:m.end()], self._buf[m.end():]
            parts.append(self._event(block))
        return self._emit(parts)

    def finish(self) -> bytes:
        """스트림 끝. 블록 끝 없이 남은 텍스트를 처리하고, 보류 꼬리가 남았으면 합성 조각으로 내보낸다."""
        parts = []
        tail = self._buf + self._decoder.decode(b"", final=True)
        self._buf = ""
        if tail:
            parts.append(self._event(tail))
        parts.append(self._flush(lambda ch: True))
        return self._emit(parts)

    @property
    def visible_text(self) -> str:
        return "".join(self._visible)

    # --- 내부 --------------------------------------------------------------
    @staticmethod
    def _emit(parts: list[str]) -> bytes:
        return "".join(parts).encode("utf-8")

    def _event(self, block: str) -> str:
        """블록 하나 → 내보낼 텍스트. 바뀌지 않았으면 block 그대로."""
        data = list(DATA_RE.finditer(block))
        if len(data) != 1:
            return block
        m = data[0]
        line_end = block.find("\n", m.end())
        if line_end == -1:
            line_end = len(block)
        payload = block[m.end():line_end].rstrip("\r")
        if self._shape.is_done(payload):
            return self._flush(lambda ch: True) + block
        try:
            obj = json.loads(payload)
        except ValueError:
            return block
        if not isinstance(obj, dict):
            return block
        # 오류 이벤트: Messages·Responses `type: error`, Responses `response.failed`, Chat `{"error": {...}}`. 블록은 그대로 내보낸다.
        # 최상위만 본다 — response.completed의 `response.error: null` 같은 중첩 값은 오류가 아니다.
        if obj.get("type") in ("error", "response.failed") or isinstance(obj.get("error"), dict):
            self.failed = True
        if self._usage is not None and isinstance(raw := self._usage(obj), dict):
            self.usage_raw.update(raw)
        if self._drop is not None and self._drop(obj):
            return ""                           # 게이트웨이가 요청한 usage 조각 — 클라이언트는 요청하지 않았다(D-120)

        changed = False
        for channel, get, put in self._shape.deltas(obj):
            text = get()
            if text is None:
                continue
            # 복원을 먼저, 보류를 그 뒤에 한다. 순서를 바꾸면 조각 끝에 **완성된** 대체값이 있을 때 그 마지막 글자가
            # "다른 대체값의 앞부분"으로 보여 보류되고, 앞부분만 내보내져 복원이 깨진다(`010-8860-744` + `0`).
            restored = self._restore_channel(channel, self._pending.pop(channel, "") + text)
            keep = self._hold(restored)
            emit, tail = restored[:len(restored) - keep], restored[len(restored) - keep:]
            self._visible.append(emit)
            if tail:
                self._pending[channel] = tail
            if emit != text:
                put(emit)
                changed = True

        prefix = ""
        closes = self._shape.closes(obj)
        if closes is not None:
            for channel in [c for c in self._pending if closes(c)]:
                restored = self._restore_channel(channel, self._pending.pop(channel))
                self._visible.append(restored)
                if self._shape.inject(obj, channel, restored):
                    changed = True
                else:
                    prefix += self._shape.synthesize(channel, restored)

        if self._shape.full_text(obj):
            # 전체 텍스트를 담은 이벤트(Responses `*.done`·`response.completed`)는 문자열 값마다 복원한다 — reasoning 요약은 건너뛴다(D-112).
            # 복원 수에는 넣지 않는다(D-124): 조각으로 이미 보내고 센 텍스트를 되풀이한다 — 세면 대체값 하나가 조각·done·part·item·completed에서
            # 다섯 번 세어져, 같은 답의 비스트리밍 복원 수(1)와 어긋난다. 잔여·의심도 조각 텍스트(visible_text)에서만 센다.
            # 응답 전체(`response`)를 담은 끝 이벤트의 수는 따로 든다 — 조각 채널이 없는 항목(mcp 인자·refusal·델타 없는 상류)도 세므로
            # 비스트리밍 복원 수와 같은 단위다. 감사에는 조각에서 센 수와 큰 쪽을 적는다(relay._stream_steps).
            n = map_strings(obj, self._restore)
            if isinstance(obj.get("response"), dict):
                self.final_restored = n
            changed = n > 0 or changed
        new_payload = json.dumps(obj, ensure_ascii=False) if changed else payload
        if new_payload == payload and not prefix:
            return block
        return prefix + block[:m.end()] + new_payload + block[line_end:]

    def _restore_channel(self, channel: str, text: str) -> str:
        restored, n = self._restore(text, json_escape if self._shape.json_channel(channel) else None)
        self.restored += n
        return restored

    def _flush(self, which: Callable[[str], bool]) -> str:
        out = ""
        for channel in [c for c in self._pending if which(c)]:
            restored = self._restore_channel(channel, self._pending.pop(channel))
            self._visible.append(restored)
            out += self._shape.synthesize(channel, restored)
        return out


class ChatShape:
    """OpenAI Chat Completions `chat.completion.chunk`. 채널: `c{choice}`(content), `t{choice}.{tool index}`(도구 인자)."""

    def __init__(self) -> None:
        self.last: dict | None = None           # 마지막으로 본 조각 — 합성 조각의 id·model

    @staticmethod
    def is_done(payload: str) -> bool:
        return payload.strip() == "[DONE]"

    @staticmethod
    def json_channel(channel: str) -> bool:
        return channel.startswith("t")          # 도구 인자

    def deltas(self, obj: dict) -> list[Ref]:
        refs: list[Ref] = []
        choices = obj.get("choices")
        if not isinstance(choices, list):
            return refs
        if choices:
            self.last = obj
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            idx = choice.get("index", 0)
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            if isinstance(delta.get("content"), str):
                refs.append(ref(f"c{idx}", delta, "content"))
            for call in delta.get("tool_calls") or []:
                fn = call.get("function") if isinstance(call, dict) else None
                if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                    refs.append(ref(f"t{idx}.{call.get('index', 0)}", fn, "arguments"))
        return refs

    def closes(self, obj: dict) -> Callable[[str], bool] | None:
        done = {str(c.get("index", 0)) for c in obj.get("choices") or []
                if isinstance(c, dict) and c.get("finish_reason") is not None}
        if not done:
            return None
        return lambda ch: ch[1:].split(".")[0] in done

    def inject(self, obj: dict, channel: str, text: str) -> bool:
        idx = channel[1:].split(".")[0]
        choice = next((c for c in obj["choices"] if isinstance(c, dict) and str(c.get("index", 0)) == idx), None)
        if choice is None:
            return False
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = choice["delta"] = {}
        if channel.startswith("c"):
            delta["content"] = text + (delta.get("content") or "")
            return True
        tool_idx = int(channel.split(".", 1)[1])
        calls = delta.setdefault("tool_calls", [])
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(call, dict) and call.get("index", 0) == tool_idx and isinstance(fn, dict):
                fn["arguments"] = text + (fn.get("arguments") or "")
                return True
        calls.append({"index": tool_idx, "function": {"arguments": text}})
        return True

    def synthesize(self, channel: str, text: str) -> str:
        last = self.last or {}
        idx = int(channel[1:].split(".")[0])
        if channel.startswith("c"):
            delta: dict = {"content": text}
        else:
            delta = {"tool_calls": [{"index": int(channel.split(".", 1)[1]), "function": {"arguments": text}}]}
        obj = {**{k: last[k] for k in ("id", "created", "model", "system_fingerprint") if k in last},
               "object": "chat.completion.chunk",
               "choices": [{"index": idx, "delta": delta, "finish_reason": None}]}
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    @staticmethod
    def full_text(obj: dict) -> bool:
        return False
