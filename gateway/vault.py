"""토큰 볼트 — 마스킹한 원문 값을 **요청 단위로** '잠깐만' 보관하고, 모양 보존 대체값을 발급·복원한다.

왜 이게 위험한 물건인가:
  마스킹한다는 건 게이트웨이가 원문을 봤다는 뜻이고, 나중에 복원하려면
  그 원문을 어딘가 들고 있어야 한다는 뜻이다. 잘못 만들면 우리가 없애려던
  유출 지점을 게이트웨이 안에 새로 만드는 꼴이 된다.

그래서 세 가지를 지킨다:
  1. 메모리에만 둔다. 디스크에 절대 쓰지 않는다. 프로세스가 죽으면 같이 사라진다.
  2. 세션 단위로 격리한다. A의 대체값으로 B의 값을 꺼낼 수 없다.
     **세션 = 요청이다(D-107 A).** 예전에는 클라이언트가 보낸 sessionId가 키였고, 그것을 맞추면 남의 원문을
     꺼낼 수 있었다. 이제 게이트웨이가 요청마다 정하는 ID가 키이고 응답이 끝나면 `drop`으로 버린다.
  3. TTL·상한은 해제가 누락됐을 때의 안전망이다(idle 10분, 2,000건). 정상 경로에서는 응답 뒤 바로 비워진다.

대체값(D-107 B): `[PII:phone:1]` 같은 토큰이 아니라 `010-8419-3027` 같은 **같은 모양의 가짜 값**이다(surrogate.py).
같은 요청 안의 같은 값은 같은 대체값을 받는다 — 사용자가 전화번호를 두 번 말하면 모델도 같은 것으로 인식해야 한다.
복원은 응답을 같은 탐지 패턴(`find_all`)으로 훑어 대체값을 되찾는다 — 모델이 `010 8419 3027`로 다시 써도 숫자가 같으면
복원된다(숫자 종류는 숫자열, 이메일은 소문자, 자격 증명은 그대로가 키다). 탐지 건수에 선형이라 대체값이 수만 개여도 느려지지 않는다(D-102 #1).
실패 양상이 바뀐 것을 적어 둔다: 토큰은 실패가 눈에 보였고(`[PII:`가 남음) 대체값은 조용히 가짜 값이 남는다. 그래서
감사에 `issued`·`restored`·`residual_tokens`(복원 뒤에도 남은 대체값 수)를 남긴다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gateway import surrogate
from gateway.detectors.patterns import Finding, digits, find_all

# 스트리밍에서 조각 끝에 보류하는 꼬리의 상한. 이보다 긴 대체값(PEM)은 조각에 걸리면 복원하지 못한다 — 감사의 residual로 보인다.
MAX_HOLD = 128
DIGIT_KINDS = frozenset({"phone", "card", "rrn"})


ESCAPED_WS_RE = re.compile(r"\\[nrt]|\s")


def norm_key(kind: str, text: str) -> str:
    """복원 조회 키. 숫자 종류는 숫자열(구분자 무시), 이메일은 소문자, 자격 증명은 공백·이스케이프된 공백(`\n`)을 뺀 그대로
    (PEM은 JSON 응답 텍스트에서 줄바꿈이 `\n` 두 글자가 된다)."""
    if kind in DIGIT_KINDS:
        return digits(text)
    if kind == "email":
        return text.lower()
    return ESCAPED_WS_RE.sub("", text)


@dataclass
class _Session:
    by_value: dict[tuple[str, str], str] = field(default_factory=dict)   # (종류, 원본) → 대체값
    by_key: dict[str, str] = field(default_factory=dict)                 # norm_key(대체값) → 원본
    prefixes: set[str] = field(default_factory=set)                      # 대체값의 모든 진접두사(정규화) — 스트림 꼬리 보류용
    touched: float = field(default_factory=time.monotonic)

    @property
    def issued(self) -> int:
        return len(self.by_value)


class TokenVault:
    def __init__(self, ttl: float = 600.0, max_sessions: int = 2000) -> None:
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
        """원본 값의 대체값. 같은 세션·같은 값은 같은 대체값."""
        entry = self._get(session)
        key = (kind, value)
        if key not in entry.by_value:
            taken = {norm_key(k, v) for k, v in entry.by_value} | set(entry.by_key)
            for _ in range(20):
                token = surrogate.make(kind, value)
                nk = norm_key(kind, token)
                if token != value and nk not in taken and nk != norm_key(kind, value):
                    break
            else:   # pragma: no cover — 20번 연속 충돌은 난수가 고장 난 것이다
                raise RuntimeError("대체값을 만들지 못했다")
            entry.by_value[key] = token
            entry.by_key[nk] = value
            if len(token) <= MAX_HOLD:
                entry.prefixes.update(nk[:i] for i in range(1, len(nk)))
                if kind in DIGIT_KINDS and token.startswith("+"):
                    entry.prefixes.add("+")
        return entry.by_value[key]

    def restore(self, session: str, text: str,
                escape: Callable[[str], str] | None = None) -> tuple[str, int]:
        """텍스트 안의 대체값을 원본으로 되돌린다. (복원된 텍스트, 복원 건수)

        `escape`는 끼워 넣기 직전 원본에 적용한다. 기본은 그대로(평문). JSON 본문이면
        호출자가 JSON 문자열 이스케이프를 넘긴다 — 볼트는 본문 형식을 모른다.

        ★ 만료 검사를 **먼저** 한다(2026-09-22의 결함: TTL 뒤 복원 경로가 만료를 안 봐 원문이 그대로 돌아왔다).
        """
        self._purge_expired()
        entry = self._sessions.get(session)
        if entry is None or not entry.by_key:
            return text, 0
        entry.touched = time.monotonic()
        out: list[str] = []
        pos = count = 0
        for f in self._hits(entry, text):
            original = entry.by_key[norm_key(f.kind, text[f.start:f.end])]
            out.append(text[pos:f.start])
            out.append(escape(original) if escape else original)
            pos = f.end
            count += 1
        out.append(text[pos:])
        return "".join(out), count

    @staticmethod
    def _hits(entry: _Session, text: str) -> list[Finding]:
        return [f for f in find_all(text) if norm_key(f.kind, text[f.start:f.end]) in entry.by_key]

    def residual(self, session: str, text: str) -> int:
        """복원 뒤에도 남은 대체값 수. 0이어야 정상이며 감사 로그로 감시한다."""
        entry = self._sessions.get(session)
        return len(self._hits(entry, text)) if entry else 0

    def hold(self, session: str, text: str) -> int:
        """스트리밍용: text의 꼬리 중 대체값의 앞부분일 수 있는 가장 긴 길이(없으면 0, 최대 MAX_HOLD).

        대체값이 두 조각에 걸릴 수 있다(`010-84` / `19-3027`). 정규화한 꼬리(숫자열·소문자)가 어떤 대체값의 진접두사면
        다음 조각이 올 때까지 보류한다. 숫자 꼬리는 구분자를 무시하므로 `010-`·`010 8`도 보류된다.
        """
        entry = self._sessions.get(session)
        if entry is None or not entry.prefixes:
            return 0
        window = text[-MAX_HOLD:]
        for i in range(len(window)):
            tail = window[i:]
            if tail[0].isdigit() or tail[0] == "+":
                if all(c.isdigit() or c in "+-.() \t" for c in tail) and digits(tail) in entry.prefixes \
                        or tail == "+" and "+" in entry.prefixes:
                    return len(tail)
            elif tail.lower() in entry.prefixes or tail in entry.prefixes:
                return len(tail)
        return 0

    def issued(self, session: str) -> int:
        entry = self._sessions.get(session)
        return entry.issued if entry else 0

    def drop(self, session: str) -> None:
        self._sessions.pop(session, None)

    def clear(self) -> None:
        self._sessions.clear()

    @property
    def session_count(self) -> int:
        self._purge_expired()
        return len(self._sessions)
