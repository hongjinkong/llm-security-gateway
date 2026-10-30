"""정형 식별자·자격 증명의 **탐지 패턴** — 검사기(pii.py)와 볼트(vault.py)가 함께 쓴다(D-107 B).

여기 있는 것은 정규식과 검증식, 겹침 해소(`find_all`)뿐이다. 마스킹·복원·세션은 모르는 순수 함수들이다.
pii.py에서 옮겨 왔다(D-031~D-102의 근거는 그대로) — 볼트가 대체값을 되찾을 때 같은 패턴으로 응답을 훑어야
하므로(대체값은 같은 모양이라 같은 정규식에 걸린다) 두 모듈이 공유하는 자리가 필요했다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# --- 패턴 --------------------------------------------------------------------
# 앞뒤에 숫자·하이픈·ASCII 알파벳이 붙어 있으면 매치하지 않는다. 두 종류의 오탐을 막는다.
#  (1) 계좌번호 "302-1122-3344-55"의 앞부분만 전화번호로 오인
#  (2) 16진 인코딩 문자열 속 숫자 덩어리를 카드번호로 오인
#      예: garak encoding.InjectBase16의 "50726169726965206E6967676572"에는
#      17자리 숫자 연속이 들어 있고 Luhn을 우연히 통과한다. 이걸 마스킹하면
#      공격 프롬프트가 훼손되어 ASR이 가짜로 떨어진다(2026-08-07 실측 17건).
# 한글은 ASCII 알파벳이 아니므로 "4111-1111-1111-1111로 결제"는 그대로 탐지된다.
_NOT_ADJACENT = r"(?<![0-9A-Za-z-])"
_NOT_TRAILING = r"(?![0-9A-Za-z-])"

RRN_RE = re.compile(_NOT_ADJACENT + r"(\d{2})(\d{2})(\d{2})[-\s]?([1-8])(\d{6})" + _NOT_TRAILING)

# 카드번호: 13~19자리. 구분자는 하이픈/공백만 허용.
CARD_RE = re.compile(_NOT_ADJACENT + r"\d(?:[ -]?\d){12,18}" + _NOT_TRAILING)

# 전화번호: 반드시 0으로 시작하는 한국 접두사만. 이것만으로 계좌번호 오탐이 대부분 걸러진다.
PHONE_RE = re.compile(
    _NOT_ADJACENT + r"(?:01[016789]|02|0[3-6][1-5])[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NOT_TRAILING)
# D-107 B: 괄호 지역번호 `(02) 123-4567`·`(031) 123-4567`, 국제 전화 `+82 10 2345 6789`·`+1 415 555 2671`.
# 국제 전화는 `+`가 강한 신호다 — `+`로 시작하고 국가번호 1~3자리 뒤에 2~4개 묶음, 숫자는 모두 8~15자리(E.164)여야 한다(find_all이 센다).
PAREN_PHONE_RE = re.compile(_NOT_ADJACENT + r"\(0\d{1,2}\)[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NOT_TRAILING)
INTL_PHONE_RE = re.compile(
    r"(?<![0-9A-Za-z+-])\+\d{1,3}(?:[-.\s]?\(?\d{1,4}\)?)(?:[-.\s]?\d{2,4}){1,3}" + _NOT_TRAILING)

# 로컬 파트는 64자까지(RFC 5321 상한). 2026-10-08 이전에는 `+`였는데, `@` 없는 긴 영숫자 줄에서
# 시작 위치마다 끝까지 다시 훑어 입력 길이의 제곱으로 느려졌다 — 40KB 한 줄에 1.9초, 워커 1개라
# 그동안 게이트웨이 전체가 멈춘다(D-099). 64자 안의 주소는 예전과 같은 구간이 잡힌다.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 기밀정보(자격 증명) — 형식이 확실한 것만 잡는다(D-099). 접두사가 고정된 키와 개인 키 블록이다.
# 엔트로피로 "비밀 같은 문자열"을 추측하지 않는다: base64·hex 공격 문자열을 비밀로 오인해 가리면
# 공격 프롬프트가 훼손되어 ASR이 가짜로 떨어진다(위 카드번호 오탐과 같은 함정).
# 개인 키 본문은 `-----END`·큰따옴표를 만나거나 8,192자에서 멈춘다. 역슬래시는 다음 글자와 짝으로 먹는다 —
# 옛 경로의 재직렬화 텍스트에서 `\"`의 역슬래시만 먹고 멈추면 따옴표가 문자열 밖으로 새어 JSON이 깨졌다(D-102). END가 없어도 실패하지 않으므로
# 되짚기가 없다. 암호화 PEM의 `Proc-Type:` 머리줄도 본문으로 함께 가린다. 큰따옴표에서 멈추는 이유:
# 옛 경로는 JSON 본문 전체를 훑으므로, 잘린 키 뒤에서 문자열 밖(JSON 구조)까지 먹으면 본문이 깨진다.
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-[A-Za-z0-9_-]{20,}"                                     # OpenAI·Anthropic API 키
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}"                                # AWS 액세스 키 ID
    r"|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}"  # GitHub 토큰
    r"|AIza[0-9A-Za-z_-]{35}"                                    # Google API 키
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"                             # Slack 토큰
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"   # JWT
    r")(?![A-Za-z0-9_-])"
    r'|-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----(?:[^-"\\]|\\[\s\S]|-(?!----END)){0,8192}'
    r"(?:-----END [A-Z ]{0,40}PRIVATE KEY-----)?")

# 겹치는 후보가 생겼을 때의 우선순위(작을수록 우선). 주민번호 13자리는 카드 패턴에도 걸린다.
# 자격 증명이 맨 앞이다 — 키 안의 숫자 덩어리가 따로 잡혀 키가 조각으로 남으면 안 된다.
PRIORITY = {"secret": 0, "rrn": 1, "card": 2, "phone": 3, "email": 4}

_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_CENTURY = {"1": 1900, "2": 1900, "3": 2000, "4": 2000,
            "5": 1900, "6": 1900, "7": 2000, "8": 2000}


@dataclass(frozen=True)
class Finding:
    """탐지 결과. **원본 값을 담지 않는다**(D-029: 로그에 평문 금지)."""

    kind: str          # rrn | card | phone | email | secret
    start: int
    end: int
    confidence: str    # strong | weak

    def as_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end,
                "len": self.end - self.start, "confidence": self.confidence}


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def rrn_checksum_ok(d: str) -> bool:
    """구 체계 검증번호. 2020-10 이후 발급분은 여기서 False가 나오는 게 정상이다."""
    if len(d) != 13:
        return False
    total = sum(int(a) * w for a, w in zip(d[:12], _RRN_WEIGHTS))
    return (11 - total % 11) % 10 == int(d[12])


def rrn_date_ok(yy: str, mm: str, dd: str, gender: str) -> bool:
    base = _CENTURY.get(gender)
    if base is None:
        return False
    try:
        date(base + int(yy), int(mm), int(dd))
    except ValueError:
        return False
    return True


def luhn_ok(d: str) -> bool:
    total, parity = 0, len(d) % 2
    for i, ch in enumerate(d):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def find_all(text: str) -> list[Finding]:
    """겹치지 않는 탐지 결과를 위치 순으로 돌려준다.

    종류마다 우선순위가 다르고(PRIORITY), 한 종류의 매치는 finditer가 왼쪽부터 겹치지 않게 내놓는다.
    그래서 우선순위 순으로 종류를 돌며 이미 자리 잡은 구간(위치 순)과 두 포인터로 한 번만 비교한다 —
    탐지 건수에 선형이다. 결과는 예전 방식(후보 전체를 우선순위·길이·위치로 정렬해 탐욕적으로 고르기)과 같다.
    2026-10-29 이전에는 후보마다 자리 잡은 구간 전체를 훑어 건수의 제곱으로 느려졌다 — 전화번호 2만 개(273KB)에
    4초, 1MiB에 60초. 워커 1개라 그동안 게이트웨이 전체가 멈춘다(D-102).
    """
    by_kind: dict[str, list[Finding]] = {k: [] for k in PRIORITY}

    for m in SECRET_RE.finditer(text):
        by_kind["secret"].append(Finding("secret", m.start(), m.end(), "strong"))

    for m in RRN_RE.finditer(text):
        yy, mm, dd, gender, tail = m.groups()
        if not rrn_date_ok(yy, mm, dd, gender):
            continue
        conf = "strong" if rrn_checksum_ok(digits(m.group(0))) else "weak"
        by_kind["rrn"].append(Finding("rrn", m.start(), m.end(), conf))

    for m in CARD_RE.finditer(text):
        d = digits(m.group(0))
        if 13 <= len(d) <= 19 and luhn_ok(d):
            by_kind["card"].append(Finding("card", m.start(), m.end(), "strong"))

    for m in PHONE_RE.finditer(text):
        by_kind["phone"].append(Finding("phone", m.start(), m.end(), "strong"))
    for m in PAREN_PHONE_RE.finditer(text):
        by_kind["phone"].append(Finding("phone", m.start(), m.end(), "strong"))
    for m in INTL_PHONE_RE.finditer(text):
        if 8 <= len(digits(m.group(0))) <= 15:
            by_kind["phone"].append(Finding("phone", m.start(), m.end(), "strong"))
    by_kind["phone"].sort(key=lambda f: f.start)       # 세 패턴을 합쳤으므로 위치 순으로 되돌린다

    for m in EMAIL_RE.finditer(text):
        by_kind["email"].append(Finding("email", m.start(), m.end(), "strong"))

    taken: list[Finding] = []
    for kind in sorted(PRIORITY, key=PRIORITY.__getitem__):
        taken = _merge_free(taken, _disjoint(by_kind[kind]))
    return taken


def _disjoint(found: list[Finding]) -> list[Finding]:
    """같은 종류 안에서 겹치는 매치(세 전화 패턴)는 앞의 것을 남긴다 — `_merge_free`는 겹치지 않는 목록을 전제한다."""
    out: list[Finding] = []
    for f in found:
        if out and f.start < out[-1].end:
            continue
        out.append(f)
    return out


def _merge_free(taken: list[Finding], cands: list[Finding]) -> list[Finding]:
    """taken(위치 순, 서로 겹치지 않음)에 cands(위치 순, 서로 겹치지 않음) 중 taken과 겹치지 않는 것만
    더해 위치 순으로 돌려준다. 두 목록을 각각 한 번씩만 지난다."""
    out: list[Finding] = []
    i = 0
    for c in cands:
        while i < len(taken) and taken[i].end <= c.start:
            out.append(taken[i])
            i += 1
        if i < len(taken) and taken[i].start < c.end:
            continue          # 더 높은 우선순위가 이미 차지한 자리
        out.append(c)
    out.extend(taken[i:])
    return out
