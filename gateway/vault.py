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
  3. TTL·상한은 해제가 누락됐을 때의 안전망이다(idle = 상류 타임아웃 + 60초, 2,000건). 정상 경로에서는 응답 뒤 바로 비워진다.
     상한을 넘으면 진행 중인 세션을 밀어내지 않고 새 세션을 거절한다(`VaultFull`, D-110) — 밀어내면 그 응답의 복원이 조용히 깨진다.

대체값(D-107 B): `[PII:phone:1]` 같은 토큰이 아니라 `010-8419-3027` 같은 **같은 모양의 가짜 값**이다(surrogate.py).
대체값은 결정적이다(D-111): 시드 = HMAC-SHA256(대체값 키, 종류 + "\0" + 정규화 원문). 같은 키·같은 원문은 요청이 달라도 같은 대체값이라
둘째 턴부터 이력의 바이트가 바뀌지 않는다 — Anthropic thinking 서명과 프롬프트 캐시가 깨지지 않는다. 키가 없으면(테스트) 볼트마다 무작위 키다.
복원은 응답을 같은 탐지 패턴(`find_all`)으로 훑어 대체값을 되찾는다 — 모델이 `010 8419 3027`로 다시 써도 숫자가 같으면
복원된다(숫자 종류는 숫자열, 이메일은 소문자, 자격 증명은 그대로가 키다). 탐지 건수에 선형이라 대체값이 수만 개여도 느려지지 않는다(D-102 #1).
실패 양상이 바뀐 것을 적어 둔다: 토큰은 실패가 눈에 보였고(`[PII:`가 남음) 대체값은 조용히 가짜 값이 남는다. 그래서
감사에 `issued`·`restored`·`residual_tokens`(복원 뒤에도 남은 대체값 수)를 남긴다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import re
import secrets
import time
from collections.abc import Callable, Iterator
from typing import Any
from dataclasses import dataclass, field

from gateway import surrogate
from gateway.detectors.patterns import Finding, digits, find_all

# 스트림 보류(D-110): 상한은 그 세션이 발급한 가장 긴 대체값 길이, 그 상한의 상한이 HOLD_CAP이다. 그보다 긴 대체값은 조각에 걸리면
# 복원하지 못한다 — 감사의 residual로 보인다. SHORT 이하의 비자격 증명은 진접두사 집합으로, 자격 증명과 더 긴 것은 KMP로 꼬리를 본다.
HOLD_CAP = 16 * 1024
SHORT = 128
PURGE_EVERY = 1.0      # 만료 정리 간격(초). 발급·복원마다 세션 전체를 훑으면 세션 수 × 발급 수가 된다(D-110)
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


# 모델의 사고 과정(D-112). 요청 마스킹도 응답 복원도 하지 않는다 — Anthropic thinking의 signature는 그 바이트에 묶여 있고,
# 복원한 텍스트가 다음 턴에 돌아오면 원래 값이 thinking 안에 담겨 상류로 간다.
UNTOUCHED_TYPES = frozenset({"thinking", "redacted_thinking", "reasoning"})


# 문자열 안에 JSON을 담는 필드(Chat·Responses 도구 인자, D-113). 복원한 값은 안쪽 JSON의 문자열 이스케이프로 끼운다.
INNER_JSON_KEYS = frozenset({"arguments"})


def json_escape(value: str) -> str:
    """JSON 문자열 리터럴 안에 넣을 형태(따옴표 없이). 원래 값의 줄바꿈·따옴표가 JSON을 깨지 않게 한다."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


def _parses(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


Restore = Callable[[str, Callable[[str], str] | None], tuple[str, int]]   # (값, escape) → (복원된 값, 건수)


def map_strings(obj: Any, fn: Restore) -> int:
    """obj 안의 문자열 값을 fn으로 바꾼다(제자리, 키는 그대로). 사고 과정 객체는 통째로 건너뛴다. 바꾼 건수의 합.

    도구 인자(INNER_JSON_KEYS)는 안쪽 JSON 이스케이프로 **텍스트 그대로** 복원한다 — 모델이 쓴 인자 바이트(공백·순서)가
    다음 턴 이력이 되므로 다시 직렬화하지 않는다. 그렇게 복원한 뒤 JSON이 깨지면(숫자 자리의 대체값 등) 그 인자만
    파싱 → 문자열 값마다 복원 → 다시 직렬화한다(D-113)."""
    if isinstance(obj, dict):
        if obj.get("type") in UNTOUCHED_TYPES:
            return 0
        items = list(obj.items())
    elif isinstance(obj, list):
        items = list(enumerate(obj))
    else:
        return 0
    total = 0
    for k, v in items:
        if isinstance(v, str):
            if k in INNER_JSON_KEYS:
                new, n = fn(v, json_escape)
                if n and _parses(v) and not _parses(new):
                    inner = json.loads(v)
                    n = map_strings(inner, fn)
                    new = json.dumps(inner, ensure_ascii=False)
            else:
                new, n = fn(v, None)
            total += n
            if new != v:
                obj[k] = new
        else:
            total += map_strings(v, fn)
    return total


def strings(obj: Any) -> Iterator[str]:
    """obj 안의 문자열 값(사고 과정 밖) — 사용자에게 복원된 채로 보이는 텍스트."""
    if isinstance(obj, dict):
        if obj.get("type") in UNTOUCHED_TYPES:
            return
        values: Any = obj.values()
    elif isinstance(obj, list):
        values = obj
    else:
        return
    for v in values:
        if isinstance(v, str):
            yield v
        else:
            yield from strings(v)


DIGIT_RUN_RE = re.compile(r"\d{4,}")
WORD_RE = re.compile(r"[A-Za-z0-9._%+-]{4,}")


class VaultFull(RuntimeError):
    """세션 상한에 닿았다. 게이트웨이는 503으로 거절한다(D-110)."""


def _failure(p: str) -> list[int]:
    """KMP 실패 함수: f[i] = p[:i+1]의 진접두사이자 접미사인 것 중 가장 긴 길이."""
    f, k = [0] * len(p), 0
    for i in range(1, len(p)):
        while k and p[i] != p[k]:
            k = f[k - 1]
        if p[i] == p[k]:
            k += 1
        f[i] = k
    return f


def _suffix_prefix(text: str, p: str, f: list[int]) -> int:
    """text의 접미사 중 p의 진접두사인 가장 긴 길이(KMP 자동자, O(len(text)))."""
    k = 0
    for c in text:
        while k and (k == len(p) or p[k] != c):
            k = f[k - 1]
        if p[k] == c:
            k += 1
    return k if k < len(p) else 0


def _normalized(text: str) -> tuple[str, list[int]]:
    """자격 증명의 norm_key처럼 공백·이스케이프된 공백을 뺀 텍스트와, 남은 글자마다의 원래 위치."""
    keep: list[str] = []
    pos: list[int] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and text[i + 1:i + 2] in ("n", "r", "t", ""):
            i += 2                  # `\n` 같은 이스케이프, 또는 조각 끝의 역슬래시(다음 조각에서 `\n`이 될 수 있다 — D-113)
            continue
        if not text[i].isspace():
            keep.append(text[i])
            pos.append(i)
        i += 1
    return "".join(keep), pos


@dataclass
class _Session:
    by_value: dict[tuple[str, str], str] = field(default_factory=dict)   # (종류, 원본) → 대체값
    by_key: dict[str, str] = field(default_factory=dict)                 # norm_key(대체값) → 원본
    taken: set[str] = field(default_factory=set)                         # 발급에 쓸 수 없는 정규화 키(원본·대체값) — O(1) 충돌 검사
    prefixes: set[str] = field(default_factory=set)                      # SHORT 이하 대체값의 모든 진접두사(정규화) — 스트림 꼬리 보류용
    long: list[tuple[str, list[int]]] = field(default_factory=list)     # SHORT보다 긴 대체값의 (정규화 키, KMP 실패 함수)
    longest: int = 0                                                     # 발급한 가장 긴 대체값 길이 — 스트림 보류 상한
    touched: float = field(default_factory=time.monotonic)

    @property
    def issued(self) -> int:
        return len(self.by_value)


class TokenVault:
    def __init__(self, ttl: float = 600.0, max_sessions: int = 2000, key: bytes | None = None) -> None:
        self.ttl = ttl
        self.max_sessions = max_sessions
        self._key = key or secrets.token_bytes(32)      # 대체값 키(GATEWAY_SURROGATE_KEY). 법률 검토 전까지 PIPA '추가정보'로 다룬다(D-111)
        self._sessions: dict[str, _Session] = {}
        self._purged = float("-inf")

    # --- 내부 ---------------------------------------------------------------
    def _purge_expired(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._purged < min(PURGE_EVERY, self.ttl):
            return
        self._purged = now
        for sid in [s for s, e in self._sessions.items() if now - e.touched > self.ttl]:
            del self._sessions[sid]

    def _live(self, session: str) -> _Session | None:
        """만료되지 않은 세션. 정리 주기와 무관하게 만료를 본다 — TTL 뒤에 복원되면 안 된다(2026-09-22의 결함)."""
        entry = self._sessions.get(session)
        if entry is not None and time.monotonic() - entry.touched > self.ttl:
            del self._sessions[session]
            return None
        return entry

    def _get(self, session: str) -> _Session:
        self._purge_expired()
        entry = self._live(session)
        if entry is None:
            if len(self._sessions) >= self.max_sessions:
                self._purge_expired(force=True)
            if len(self._sessions) >= self.max_sessions:
                # 진행 중인 세션을 밀어내지 않는다 — 밀어내면 그 응답의 복원이 조용히 깨진다(D-110). 무한히 쌓이지도 않는다.
                raise VaultFull(f"볼트 세션 상한 {self.max_sessions}")
            entry = self._sessions[session] = _Session()
        entry.touched = time.monotonic()
        return entry

    def _rng(self, kind: str, norm: str, attempt: int) -> random.Random:
        msg = f"{kind}\0{norm}" + (f"\0{attempt}" if attempt else "")
        return random.Random(int.from_bytes(hmac.new(self._key, msg.encode("utf-8"), hashlib.sha256).digest(), "big"))

    # --- 공개 API -----------------------------------------------------------
    def token_for(self, session: str, kind: str, value: str) -> str:
        """원본 값의 대체값. 같은 세션·같은 값은 같은 대체값."""
        entry = self._get(session)
        key = (kind, value)
        if key not in entry.by_value:
            own = norm_key(kind, value)
            entry.taken.add(own)
            # ponytail: 같은 요청 안에서 다른 원문과 대체값이 겹치면 카운터를 붙여 다시 만든다 — 그 값만 다른 턴과 바이트가 달라질 수 있다
            # (턴마다 겹치는 상대가 다를 때). 같은 종류·같은 모양 안의 겹침은 드물다. 늘 같게 하려면 겹침을 원문 쌍의 순서로 정해야 한다.
            for attempt in range(20):
                token = surrogate.make(kind, value, self._rng(kind, own, attempt))
                nk = norm_key(kind, token)
                if token != value and nk not in entry.taken:
                    break
            else:   # pragma: no cover — 20번 연속 충돌은 생성 규칙이 고장 난 것이다
                raise RuntimeError("대체값을 만들지 못했다")
            entry.by_value[key] = token
            entry.by_key[nk] = value
            entry.taken.add(nk)
            if kind != "secret" and len(nk) <= SHORT:
                entry.prefixes.update(nk[:i] for i in range(1, len(nk)))
                if kind in DIGIT_KINDS and token.startswith("+"):
                    entry.prefixes.add("+")
            elif len(token) <= HOLD_CAP:     # 자격 증명은 길이와 무관하게 — 공백·`\n` 이스케이프를 정규화해야 PEM 앞부분이 보인다(D-113)
                entry.long.append((nk, _failure(nk)))
            if len(token) <= HOLD_CAP:
                entry.longest = max(entry.longest, len(token))
        return entry.by_value[key]

    def restore(self, session: str, text: str,
                escape: Callable[[str], str] | None = None) -> tuple[str, int]:
        """텍스트 안의 대체값을 원본으로 되돌린다. (복원된 텍스트, 복원 건수)

        `escape`는 끼워 넣기 직전 원본에 적용한다. 기본은 그대로(평문). JSON 본문이면
        호출자가 JSON 문자열 이스케이프를 넘긴다 — 볼트는 본문 형식을 모른다.

        ★ 만료 검사를 **먼저** 한다(2026-09-22의 결함: TTL 뒤 복원 경로가 만료를 안 봐 원문이 그대로 돌아왔다).
        """
        self._purge_expired()
        entry = self._live(session)
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
        entry = self._live(session)
        return len(self._hits(entry, text)) if entry else 0

    def hold(self, session: str, text: str) -> int:
        """스트리밍용: text의 꼬리 중 대체값의 앞부분일 수 있는 가장 긴 길이(없으면 0, 최대 이 세션의 가장 긴 대체값 길이).

        대체값이 두 조각에 걸릴 수 있다(`010-84` / `19-3027`). 정규화한 꼬리(숫자열·소문자)가 어떤 대체값의 진접두사면
        다음 조각이 올 때까지 보류한다. 숫자 꼬리는 구분자를 무시하므로 `010-`·`010 8`도 보류된다.
        SHORT보다 긴 대체값은 공백을 뺀 꼬리에 KMP 자동자를 돌려 본다(D-110).
        """
        entry = self._live(session)
        if entry is None or not (entry.prefixes or entry.long):
            return 0
        best = 0
        window = text[-SHORT:] if entry.prefixes else ""
        for i in range(len(window)):
            tail = window[i:]
            if tail[0].isdigit() or tail[0] == "+":
                if all(c.isdigit() or c in "+-.() \t" for c in tail) and digits(tail) in entry.prefixes \
                        or tail == "+" and "+" in entry.prefixes:
                    best = len(tail)
                    break
            elif tail.lower() in entry.prefixes or tail in entry.prefixes:
                best = len(tail)
                break
        if entry.long:
            window = text[-2 * entry.longest:]       # JSON 인자 채널에서는 이스케이프(`\n`)로 원래보다 길다
            norm, pos = _normalized(window)
            for nk, f in entry.long:
                k = _suffix_prefix(norm[-(len(nk) - 1):], nk, f)
                if k:
                    best = max(best, len(window) - pos[len(norm) - k])
        return best

    def suspect(self, session: str, text: str) -> int:
        """복원 뒤 사용자에게 보이는 text의 의심 잔여(D-113): 남은 대체값 수 + 대체값이 통째로는 없는데 그 식별 조각
        (전화·카드의 끝 4자리, 이메일 로컬파트)이 원래 값에는 없이 나타난 대체값 수. 조각은 한 번 훑어 집합으로 본다."""
        entry = self._live(session)
        if entry is None:
            return 0
        hits = self._hits(entry, text)
        present = {norm_key(f.kind, text[f.start:f.end]) for f in hits}
        quads = {m.group(0)[i:i + 4] for m in DIGIT_RUN_RE.finditer(text) for i in range(len(m.group(0)) - 3)}
        words = {w.lower() for w in WORD_RE.findall(text)}
        n = len(hits)
        for (kind, original), token in entry.by_value.items():
            if norm_key(kind, token) in present:
                continue
            if kind in ("phone", "card"):
                frag, seen = digits(token)[-4:], quads
            elif kind == "email":
                frag, seen = token.rpartition("@")[0].lower(), words
            else:
                continue
            if len(frag) >= 4 and frag in seen and frag not in original.lower():
                n += 1
        return n

    def touch(self, session: str) -> None:
        """세션의 만료 시계를 갱신한다 — 스트림 조각마다(ping·thinking 포함) 부른다(D-110)."""
        entry = self._live(session)
        if entry is not None:
            entry.touched = time.monotonic()

    def issued(self, session: str) -> int:
        entry = self._live(session)
        return entry.issued if entry else 0

    def drop(self, session: str) -> None:
        self._sessions.pop(session, None)

    def clear(self) -> None:
        self._sessions.clear()

    @property
    def session_count(self) -> int:
        self._purge_expired(force=True)
        return len(self._sessions)
