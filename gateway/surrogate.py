"""모양 보존 대체값(surrogate) 생성 — 원문과 같은 모양의 가짜 값(D-107 B).

`[PII:phone:1]` 같은 토큰 대신 `010-8419-3027` 같은 값을 상류에 보낸다. 모델은 그것을 보통의 값으로 다루고
(눈치채지 않고, 괄호를 떨어뜨릴 일도 없고) 도구 인자에도 그대로 쓴다. 복원은 볼트가 같은 탐지 패턴으로 응답을
훑어 대체값을 되찾는 방식이라(vault.py), 대체값은 **반드시 자기 종류의 패턴에 다시 걸려야 한다** — 카드는 Luhn을
맞추고 주민번호는 유효한 생년월일을 만드는 이유다.

규칙(문서 D-107 §2 B):
  phone   국내 접두사(010·02·031…)와 구분자·괄호 유지, 나머지 숫자 무작위. 국제는 `+국가번호`(첫 묶음) 유지.
  card    첫 자리·구분자 유지, 중간 무작위, 마지막 자리는 Luhn.
  rrn     유효한 생년월일 무작위, 성별 자리 1~4 무작위, 뒤 6자리 무작위(검증번호는 맞추지 않는다 — 2020-10 이후 발급분과 같다).
  email   로컬파트: 글자→무작위 소문자, 숫자→무작위 숫자, 구두점 유지. 도메인은 RFC 2606 예약 도메인(example.com·.net·.org) 중 하나(D-113) —
          복원에 실패해도 실제 제3자의 주소가 되지 않는다.
  secret  알려진 접두사(`sk-`·`sk-proj-`·`AKIA`·`ghp_`·`AIza`·`xoxb-`·JWT의 `eyJ`) 유지, 나머지는 같은 글자 부류의 무작위.
          PEM은 BEGIN/END 줄 유지, 본문은 같은 부류의 무작위.
  D-117   frn은 주민번호와 같고 성별 5~8. passport는 종류 글자 유지·같은 부류 무작위. driver는 지역 2자리, account는 앞 3자리 유지.
          brn은 앞 5자리(세무서·구분), crn은 앞 7자리 유지에 검증 숫자 계산. ipv4는 첫 묶음 유지, 나머지는 무작위 공인 주소.
난수는 호출자가 넘긴다(D-111). 볼트는 값마다 `random.Random(HMAC-SHA256(대체값 키, 종류 + "\0" + 정규화 값))`을 넘기므로
같은 키·같은 원문은 언제나 같은 대체값이 된다 — 다음 턴 이력의 바이트가 바뀌지 않는다(thinking 서명·프롬프트 캐시).
`make`를 rng 없이 부르면(모양 규칙 테스트) 시스템 난수를 쓴다.
"""
from __future__ import annotations

import ipaddress
import random
import re
import secrets
import string
from collections.abc import Callable

from gateway.detectors.patterns import brn_check, crn_check, digits

_SYSTEM = secrets.SystemRandom()

WS_RE = re.compile(r"\s")
KR_PREFIX_RE = re.compile(r"^\(?(?:01[016789]|02|0[3-6][1-5]|070)\)?")
INTL_PREFIX_RE = re.compile(r"^\+\d{1,3}(?=[-.\s(]|$)|^\+\d{1,2}")   # `+82 10…`은 `+82`, `+821023…`은 `+82`
SECRET_PREFIX_RE = re.compile(
    r"^(?:sk-(?:[a-z]+-)?|AKIA|ASIA|gh[pousr]_|github_pat_|AIza|xox[abprs]-)")
PEM_RE = re.compile(r"^(-----BEGIN [A-Z ]*PRIVATE KEY-----)([\s\S]*?)(-----END [A-Z ]*PRIVATE KEY-----)?$")


def _scramble(s: str, rng: random.Random, keep: int = 0) -> str:
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
            out.append(rng.choice(string.digits))
        elif c.islower():
            out.append(rng.choice(string.ascii_lowercase))
        elif c.isupper():
            out.append(rng.choice(string.ascii_uppercase))
        else:
            out.append(c)
    return "".join(out)


def _random_digits_in(s: str, rng: random.Random, keep_first: int = 0, keep_last: int = 0) -> list[str]:
    """s의 숫자 자리만 무작위로 바꾼 글자 목록. 앞 keep_first개·뒤 keep_last개 숫자는 그대로."""
    chars = list(s)
    idx = [i for i, c in enumerate(chars) if c.isdigit()]
    for n, i in enumerate(idx):
        if n < keep_first or n >= len(idx) - keep_last:
            continue
        chars[i] = rng.choice(string.digits)
    return chars


def phone(value: str, rng: random.Random) -> str:
    # 줄바꿈·탭 구분자는 빈칸으로 — JSON 응답 텍스트에서는 `\n` 두 글자로 이스케이프돼 같은 패턴에 다시 걸리지 않는다(복원 실패).
    value = WS_RE.sub(" ", value)
    m = INTL_PREFIX_RE.match(value) or KR_PREFIX_RE.match(value)
    keep = len(digits(m.group(0))) if m else 0
    return "".join(_random_digits_in(value, rng, keep_first=keep))


def _with_check(chars: list[str], check: Callable[[str], int]) -> str:
    """마지막 숫자 자리를 그 앞 숫자들의 검증 숫자로 바꾼 텍스트."""
    last = max(i for i, c in enumerate(chars) if c.isdigit())
    chars[last] = str(check(digits("".join(chars))[:-1]))
    return "".join(chars)


def _luhn(body: str) -> int:
    """본문 뒤에 붙였을 때 Luhn 합이 10의 배수가 되는 한 자리."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10


def card(value: str, rng: random.Random) -> str:
    return _with_check(_random_digits_in(value, rng, keep_first=1, keep_last=1), _luhn)


def rrn(value: str, rng: random.Random, genders: str = "1234") -> str:
    sep = WS_RE.sub(" ", value[6:-7])                   # `-`, 공백, 또는 없음
    gender = rng.choice(genders)
    yy = rng.randint(40, 99) if gender in "1256" else rng.randint(0, 20)
    mm, dd = rng.randint(1, 12), rng.randint(1, 28)
    return f"{yy:02d}{mm:02d}{dd:02d}{sep}{gender}{rng.randint(0, 999999):06d}"


def frn(value: str, rng: random.Random) -> str:
    return rrn(value, rng, "5678")


def crn(value: str, rng: random.Random) -> str:
    # 앞 7자리(등기소·법인 종류·일련번호 첫 자리)를 지키면 주민번호 꼴인지가 원문과 같다 — 같은 종류로 다시 잡힌다
    return _with_check(_random_digits_in(value, rng, keep_first=7, keep_last=1), crn_check)


def brn(value: str, rng: random.Random) -> str:
    return _with_check(_random_digits_in(value, rng, keep_first=5, keep_last=1), brn_check)


def driver(value: str, rng: random.Random) -> str:
    return "".join(_random_digits_in(value, rng, keep_first=2))


def account(value: str, rng: random.Random) -> str:
    return "".join(_random_digits_in(value, rng, keep_first=3))


def passport(value: str, rng: random.Random) -> str:
    return _scramble(value, rng, keep=1)


def ipv4(value: str, rng: random.Random) -> str:
    head = value.split(".")[0]
    for _ in range(1000):          # 공인 주소만 탐지하므로 대체값도 공인 주소여야 다시 잡힌다
        s = f"{head}.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)}"
        ip = ipaddress.IPv4Address(s)
        if s != value and ip.is_global and not ip.is_multicast:
            return s
    raise ValueError(f"공인 대체 주소를 만들지 못했다: {head}.x.x.x")


RESERVED_DOMAINS = ("example.com", "example.net", "example.org")


def email(value: str, rng: random.Random) -> str:
    local = value.rpartition("@")[0]
    return _scramble(local, rng).lower() + "@" + rng.choice(RESERVED_DOMAINS)


def secret(value: str, rng: random.Random) -> str:
    m = PEM_RE.match(value)
    if m:                                               # BEGIN/END 줄은 그대로, 본문만 무작위(줄바꿈·`\n` 이스케이프·`=`는 유지)
        return m.group(1) + _scramble(m.group(2), rng) + (m.group(3) or "")
    if value.startswith("eyJ"):                         # JWT: 세 조각 각각 `eyJ`(= `{"`)를 지킨다
        return ".".join(_scramble(part, rng, keep=3 if i < 2 else 0) for i, part in enumerate(value.split(".")))
    m = SECRET_PREFIX_RE.match(value)
    return _scramble(value, rng, keep=len(m.group(0)) if m else 0)


MAKERS = {"phone": phone, "card": card, "rrn": rrn, "email": email, "secret": secret, "frn": frn, "crn": crn, "brn": brn,
          "driver": driver, "account": account, "passport": passport, "ipv4": ipv4}


def make(kind: str, value: str, rng: random.Random | None = None) -> str:
    return MAKERS[kind](value, rng or _SYSTEM)
