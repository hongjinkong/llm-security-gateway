"""모양 보존 대체값(surrogate) 생성 — 원문과 같은 모양의 가짜 값(D-107 B).

`[PII:phone:1]` 같은 토큰 대신 `010-8419-3027` 같은 값을 상류에 보낸다. 모델은 그것을 보통의 값으로 다루고
(눈치채지 않고, 괄호를 떨어뜨릴 일도 없고) 도구 인자에도 그대로 쓴다. 복원은 볼트가 같은 탐지 패턴으로 응답을
훑어 대체값을 되찾는 방식이라(vault.py), 대체값은 **반드시 자기 종류의 패턴에 다시 걸려야 한다** — 카드는 Luhn을
맞추고 주민번호는 유효한 생년월일을 만드는 이유다.

규칙(문서 D-107 §2 B):
  phone   국내 접두사(010·02·031…)와 구분자·괄호 유지, 나머지 숫자 무작위. 국제는 `+국가번호`(첫 묶음) 유지.
  card    첫 자리·구분자 유지, 중간 무작위, 마지막 자리는 Luhn.
  rrn     유효한 생년월일 무작위, 성별 자리 1~4 무작위, 뒤 6자리 무작위(검증번호는 맞추지 않는다 — 2020-10 이후 발급분과 같다).
  email   글자→무작위 소문자, 숫자→무작위 숫자, 구두점·`@`·TLD 유지.
  secret  알려진 접두사(`sk-`·`sk-proj-`·`AKIA`·`ghp_`·`AIza`·`xoxb-`·JWT의 `eyJ`) 유지, 나머지는 같은 글자 부류의 무작위.
          PEM은 BEGIN/END 줄 유지, 본문은 같은 부류의 무작위.
난수는 `secrets`(예측 불가가 필요한 건 아니지만 비용이 없다).
"""
from __future__ import annotations

import re
import secrets
import string

from gateway.detectors.patterns import digits

_rng = secrets.SystemRandom()

WS_RE = re.compile(r"\s")
KR_PREFIX_RE = re.compile(r"^\(?(?:01[016789]|02|0[3-6][1-5])\)?")
INTL_PREFIX_RE = re.compile(r"^\+\d{1,3}(?=[-.\s(]|$)|^\+\d{1,2}")   # `+82 10…`은 `+82`, `+821023…`은 `+82`
SECRET_PREFIX_RE = re.compile(
    r"^(?:sk-(?:[a-z]+-)?|AKIA|ASIA|gh[pousr]_|github_pat_|AIza|xox[abprs]-)")
PEM_RE = re.compile(r"^(-----BEGIN [A-Z ]*PRIVATE KEY-----)([\s\S]*?)(-----END [A-Z ]*PRIVATE KEY-----)?$")


def _scramble(s: str, keep: int = 0) -> str:
    """앞 `keep`자는 그대로, 나머지는 글자 부류(숫자·소문자·대문자)를 지킨 무작위. 그 밖의 문자는 그대로."""
    out = list(s[:keep])
    skip = False
    for c in s[keep:]:
        if skip:                                        # 역슬래시 짝(`\n`·`\"`)은 그대로 — 옛 경로의 재직렬화 본문에서 JSON이 깨진다
            out.append(c)
            skip = False
        elif c == "\\":
            out.append(c)
            skip = True
        elif c.isdigit():
            out.append(_rng.choice(string.digits))
        elif c.islower():
            out.append(_rng.choice(string.ascii_lowercase))
        elif c.isupper():
            out.append(_rng.choice(string.ascii_uppercase))
        else:
            out.append(c)
    return "".join(out)


def _random_digits_in(s: str, keep_first: int = 0, keep_last: int = 0) -> list[str]:
    """s의 숫자 자리만 무작위로 바꾼 글자 목록. 앞 keep_first개·뒤 keep_last개 숫자는 그대로."""
    chars = list(s)
    idx = [i for i, c in enumerate(chars) if c.isdigit()]
    for n, i in enumerate(idx):
        if n < keep_first or n >= len(idx) - keep_last:
            continue
        chars[i] = _rng.choice(string.digits)
    return chars


def phone(value: str) -> str:
    # 줄바꿈·탭 구분자는 빈칸으로 — JSON 응답 텍스트에서는 `\n` 두 글자로 이스케이프돼 같은 패턴에 다시 걸리지 않는다(복원 실패).
    value = WS_RE.sub(" ", value)
    m = INTL_PREFIX_RE.match(value) or KR_PREFIX_RE.match(value)
    keep = len(digits(m.group(0))) if m else 0
    return "".join(_random_digits_in(value, keep_first=keep))


def card(value: str) -> str:
    chars = _random_digits_in(value, keep_first=1, keep_last=1)
    body = digits("".join(chars))[:-1]
    # Luhn 검증 자리: 본문 뒤에 붙였을 때 합이 10의 배수가 되는 한 자리
    total = 0
    for i, ch in enumerate(reversed(body)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check = (10 - total % 10) % 10
    last = max(i for i, c in enumerate(chars) if c.isdigit())
    chars[last] = str(check)
    return "".join(chars)


def rrn(value: str) -> str:
    sep = WS_RE.sub(" ", value[6:-7])                   # `-`, 공백, 또는 없음
    gender = _rng.choice("1234")
    yy = _rng.randint(40, 99) if gender in "12" else _rng.randint(0, 20)
    mm, dd = _rng.randint(1, 12), _rng.randint(1, 28)
    return f"{yy:02d}{mm:02d}{dd:02d}{sep}{gender}{_rng.randint(0, 999999):06d}"


def email(value: str) -> str:
    local, _, domain = value.rpartition("@")
    labels = domain.split(".")
    scrambled = [_scramble(l).lower() for l in labels[:-1]] + [labels[-1]]      # TLD는 그대로
    return _scramble(local).lower() + "@" + ".".join(scrambled)


def secret(value: str) -> str:
    m = PEM_RE.match(value)
    if m:                                               # BEGIN/END 줄은 그대로, 본문만 무작위(줄바꿈·`\n` 이스케이프·`=`는 유지)
        return m.group(1) + _scramble(m.group(2)) + (m.group(3) or "")
    if value.startswith("eyJ"):                         # JWT: 세 조각 각각 `eyJ`(= `{"`)를 지킨다
        return ".".join(_scramble(part, keep=3 if i < 2 else 0) for i, part in enumerate(value.split(".")))
    m = SECRET_PREFIX_RE.match(value)
    return _scramble(value, keep=len(m.group(0)) if m else 0)


MAKERS = {"phone": phone, "card": card, "rrn": rrn, "email": email, "secret": secret}


def make(kind: str, value: str) -> str:
    return MAKERS[kind](value)
