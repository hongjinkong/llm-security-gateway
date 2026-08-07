"""토큰 볼트 — 마스킹한 원본 값을 세션 단위로 '잠깐만' 보관한다.

왜 이게 위험한 물건인가:
  마스킹한다는 건 게이트웨이가 원문을 봤다는 뜻이고, 나중에 복원하려면
  그 원문을 어딘가 들고 있어야 한다는 뜻이다. 잘못 만들면 우리가 없애려던
  유출 지점을 게이트웨이 안에 새로 만드는 꼴이 된다.

그래서 세 가지를 지킨다:
  1. 메모리에만 둔다. 디스크에 절대 쓰지 않는다. 프로세스가 죽으면 같이 사라진다.
  2. 세션 단위로 격리한다. A의 토큰으로 B의 값을 꺼낼 수 없다.
  3. TTL이 지나면 폐기한다. 오래 들고 있을 이유가 없다.

토큰 형식은 `[PII:kind:번호]`. 같은 세션에서 같은 값은 항상 같은 토큰을 받는다.
사용자가 전화번호를 두 번 말하면 모델도 같은 것으로 인식해야 하기 때문이다.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"\[PII:([a-z]+):(\d+)\]")


@dataclass
class _Session:
    by_token: dict[str, str] = field(default_factory=dict)          # 토큰 → 원본
    by_value: dict[tuple[str, str], str] = field(default_factory=dict)  # (종류,원본) → 토큰
    counter: int = 0
    touched: float = field(default_factory=time.monotonic)


class TokenVault:
    def __init__(self, ttl: float = 1800.0, max_sessions: int = 500) -> None:
        self.ttl = ttl
        self.max_sessions = max_sessions
        self._sessions: dict[str, _Session] = {}

    # --- 내부 ---------------------------------------------------------------
    def _purge_expired(self) -> None:
        now = time.monotonic()
        for sid in [s for s, e in self._sessions.items() if now - e.touched > self.ttl]:
            del self._sessions[sid]

    def _get(self, session: str) -> _Session:
        self._purge_expired()
        entry = self._sessions.get(session)
        if entry is None:
            if len(self._sessions) >= self.max_sessions:
                # 가장 오래 손대지 않은 세션부터 버린다. 무한히 쌓이면 그 자체가 취약점이다.
                oldest = min(self._sessions, key=lambda s: self._sessions[s].touched)
                del self._sessions[oldest]
            entry = self._sessions[session] = _Session()
        entry.touched = time.monotonic()
        return entry

    # --- 공개 API -----------------------------------------------------------
    def token_for(self, session: str, kind: str, value: str) -> str:
        entry = self._get(session)
        key = (kind, value)
        if key not in entry.by_value:
            entry.counter += 1
            token = f"[PII:{kind}:{entry.counter}]"
            entry.by_value[key] = token
            entry.by_token[token] = value
        return entry.by_value[key]

    def restore(self, session: str, text: str) -> tuple[str, int]:
        """텍스트 안의 토큰을 원본으로 되돌린다. (복원된 텍스트, 복원 건수)"""
        entry = self._sessions.get(session)
        if entry is None:
            return text, 0
        entry.touched = time.monotonic()
        count = 0

        def sub(m: re.Match[str]) -> str:
            nonlocal count
            original = entry.by_token.get(m.group(0))
            if original is None:
                return m.group(0)      # 모르는 토큰은 손대지 않는다
            count += 1
            return original

        return TOKEN_RE.sub(sub, text), count

    def drop(self, session: str) -> None:
        self._sessions.pop(session, None)

    def clear(self) -> None:
        self._sessions.clear()

    @property
    def session_count(self) -> int:
        self._purge_expired()
        return len(self._sessions)
