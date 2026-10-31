"""정형 식별자·자격 증명의 **탐지 패턴** — 검사기(pii.py)와 볼트(vault.py)가 함께 쓴다(D-107 B).

여기 있는 것은 정규화, 정규식과 검증식, 겹침 해소(`find_all`)뿐이다. 마스킹·복원·세션은 모르는 순수 함수들이다.
pii.py에서 옮겨 왔다(D-031~D-102의 근거는 그대로) — 볼트가 대체값을 되찾을 때 같은 패턴으로 응답을
훑어야 하므로(대체값은 같은 모양이라 같은 정규식에 걸린다) 두 모듈이 공유하는 자리가 필요했다.

탐지는 정규화한 텍스트(전각·제로폭·대시 변형, D-116)에서 하고 결과 위치는 원문으로 되돌린다. 가릴지는 `Finding.mask`가
말한다 — 문맥 없는 약한 주민번호·발급사 범위 밖 카드 꼴은 탐지는 하되(감사·복원) 가리지 않는다.
**탐지는 모양만 보고 문맥어는 가릴지만 정한다**(D-117): 볼트는 응답의 대체값을 같은 패턴으로 되찾으므로, 문맥 없이 돌아온 대체값도 잡혀야 한다.
"""
from __future__ import annotations

import bisect
import functools
import ipaddress
import re
import unicodedata
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
# 인터넷 전화 070은 D-117에 더했다(D-115 기준선에서 4/4 놓침).
PHONE_RE = re.compile(
    _NOT_ADJACENT + r"(?:01[016789]|02|0[3-6][1-5]|070)[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NOT_TRAILING)
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

# --- 한국 식별자(D-117) — 패턴·검증식은 Presidio KR 인식기(MIT)와 공개 검증식으로 대조했다(DECISIONS D-117 §1) ---
# 하이픈으로 묶은 숫자는 정규식 하나로 찾고 묶음 길이로 종류를 가른다: 사업자 3-2-5, 법인 6-7, 운전면허 2-2-6-2, 계좌는 은행별 꼴.
# 구분자 없는 꼴은 넣지 않는다 — 문맥어 없이는 흔한 숫자열이라, 응답에서 문맥 없이 돌아온 대체값을 되찾을 수 없다.
GROUPED_RE = re.compile(_NOT_ADJACENT + r"\d{2,6}(?:-\d{1,7}){1,3}" + _NOT_TRAILING)
ACCOUNT_LAYOUTS = frozenset({
    (3, 2, 4, 3), (6, 2, 6),             # 국민(옛 12자리·14자리), 우체국
    (3, 6, 2, 3),                        # 기업
    (3, 4, 4, 2), (3, 4, 4, 3),          # 농협(가상 14자리)
    (3, 2, 6), (3, 3, 6),                # 신한(옛·새)·SC제일·케이뱅크
    (4, 3, 6),                           # 우리
    (3, 6, 5), (3, 6, 3), (3, 2, 5, 1),  # 하나(옛 외환 꼴 포함)
    (4, 2, 7),                           # 카카오뱅크
    (4, 4, 4), (4, 4, 4, 1),             # 토스뱅크, 새마을금고
})
DRIVER_REGIONS = frozenset({*map(str, range(11, 27)), "28"})   # 서울 11 … 울산 26, 경기북부 28(2014-07부터 숫자, Presidio와 같다)
# 여권 종류 글자(M 일반 복수·S 단수·R 거주·O 관용·D 외교 — Presidio·Microsoft Purview 정의) + 8자리(구형) 또는 3자리 + 대문자 + 4자리(2021-12 차세대).
PASSPORT_RE = re.compile(r"(?<![0-9A-Za-z-])[MSROD](?:\d{8}|\d{3}[A-Z]\d{4})(?![0-9A-Za-z-])")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
# 앞에 영숫자·점·`_`·`-`가 붙거나 `Chrome/`처럼 글자 뒤 `/`(UA 토큰)면, 뒤에 `.숫자`가 이어지면(OID·5묶음 버전) 주소가 아니다.
IPV4_RE = re.compile(r"(?<![0-9A-Za-z._-])(?<![A-Za-z]/)" + _OCTET + r"(?:\." + _OCTET + r"){3}(?![0-9A-Za-z_-])(?!\.\d)")

# 가릴지를 정하는 문맥어(D-116). 값의 앞뒤 CONTEXT_CHARS자(정규화 텍스트) 안에 있으면 그 종류로 본다.
CONTEXT_CHARS = 20
RRN_CONTEXT_RE = re.compile(r"주민|생년|등록\s*번호|외국인|RRN|FRN|resident|alien|foreigner", re.IGNORECASE)   # 외국인등록번호도 같이
# '결제'·'승인'은 넣지 않는다 — 주문·정산 문장에 흔해 범위 밖 주문번호를 가리게 된다.
CARD_CONTEXT_RE = re.compile(r"카드|신용|비자|마스터|은련|card|credit|visa|master|amex|jcb|unionpay", re.IGNORECASE)
PASSPORT_CONTEXT_RE = re.compile(r"여권|passport", re.IGNORECASE)
ACCOUNT_CONTEXT_RE = re.compile(r"계좌|입금|송금|이체|예금|은행|뱅크|농협|신한|국민|우리|하나|기업|우체국|새마을|수협|account|bank", re.IGNORECASE)
CRN_CONTEXT_RE = re.compile(r"법인|corp", re.IGNORECASE)
VERSION_CONTEXT_RE = re.compile(r"버전|빌드|펌웨어|version|build|release|firmware", re.IGNORECASE)   # 4묶음 버전 번호는 IPv4 꼴이다

# 겹치는 후보가 생겼을 때의 우선순위(작을수록 우선). 주민번호 13자리는 카드 패턴에도 걸린다.
# 자격 증명이 맨 앞이다 — 키 안의 숫자 덩어리가 따로 잡혀 키가 조각으로 남으면 안 된다.
# D-117: 주민 꼴(실제 날짜 + 성별 1~8)은 법인번호보다 앞 — 틀려도 '가림' 쪽으로 틀린다. 계좌는 카드보다 앞(은행 꼴이 Luhn을 우연히 맞추면
# 문맥 없는 카드로 잡혀 계좌 문맥어가 있어도 못 가린다), 이메일은 여권보다 앞(`M12345678@…`의 로컬파트만 가리면 도메인이 남는다).
PRIORITY = {"secret": 0, "rrn": 1, "frn": 2, "crn": 3, "account": 4, "card": 5, "phone": 6, "driver": 7, "brn": 8,
            "email": 9, "passport": 10, "ipv4": 11}

_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_CENTURY = {"1": 1900, "2": 1900, "3": 2000, "4": 2000,
            "5": 1900, "6": 1900, "7": 2000, "8": 2000}


@dataclass(frozen=True)
class Finding:
    """탐지 결과. **원본 값을 담지 않는다**(D-029: 로그에 평문 금지). 위치는 원문 기준이다."""

    kind: str          # PRIORITY의 키 — rrn | frn | crn | account | card | phone | driver | brn | email | passport | ipv4 | secret
    start: int
    end: int
    confidence: str    # strong | weak
    mask: bool = True  # False = 감사에만 남기고 가리지 않는다(D-116). 볼트는 이것과 무관하게 복원에 쓴다

    def as_dict(self) -> dict:
        d = {"kind": self.kind, "start": self.start, "end": self.end,
             "len": self.end - self.start, "confidence": self.confidence}
        if not self.mask:
            d["mask"] = False
        return d


# --- 정규화(D-116) --------------------------------------------------------------
# 글자마다 NFKC(전각 숫자·문자·＠·NBSP), 서식 문자(Cf: 제로폭·방향 제어·태그 문자) 제거, 대시 변형은 `-`, 가운뎃점은 `.`.
_DASHES = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63")   # ‐ ‑ ‒ – — ― − ﹘ ﹣ (전각 －는 NFKC가 -로)
_DOTS = frozenset("\u00b7\u30fb\u318d")                                         # · ・ ㆍ
_SPECIAL_RE = re.compile(r"[^\x00-\x7f\uac00-\ud7a3]")                           # 바뀔 수 있는 글자 — ASCII·한글 음절 밖


@functools.lru_cache(maxsize=4096)
def _norm_char(c: str) -> str:
    if c in _DASHES:
        return "-"
    if c in _DOTS:
        return "."
    if unicodedata.category(c) == "Cf":
        return ""
    if "\u3131" <= c <= "\u318e":       # 한글 호환 자모는 그대로 — NFKC가 조합형 자모로 바꿔 인젝션 어휘를 흔든다
        return c
    return unicodedata.normalize("NFKC", c)


class Normalized:
    """정규화한 텍스트. cuts = 바뀐 원문 글자마다 (정규화 위치, 바뀐 뒤 길이, 원문 위치) — 그 사이는 원문과 1:1이다."""

    __slots__ = ("text", "cuts", "_at")

    def __init__(self, text: str, cuts: list[tuple[int, int, int]]) -> None:
        self.text, self.cuts, self._at = text, cuts, [c[0] for c in cuts]

    def _char(self, i: int) -> int:
        """정규화 위치 i의 글자를 낸 원문 글자 위치."""
        k = bisect.bisect_right(self._at, i) - 1
        if k < 0:
            return i
        at, n, orig = self.cuts[k]
        return orig if i < at + n else orig + 1 + (i - at - n)

    def span(self, start: int, end: int) -> tuple[int, int]:
        """정규화 구간 [start, end) → 그 글자들을 낸 원문 구간(사이에 지운 글자도 덮는다)."""
        return (start, end) if not self.cuts else (self._char(start), self._char(end - 1) + 1)


def normalize(text: str) -> Normalized:
    if text.isascii():
        return Normalized(text, [])
    parts: list[str] = []
    cuts: list[tuple[int, int, int]] = []
    pos = at = 0
    for m in _SPECIAL_RE.finditer(text):
        i, c = m.start(), m.group()
        rep = _norm_char(c)
        if rep == c:
            continue
        parts.append(text[pos:i])
        at += i - pos
        cuts.append((at, len(rep), i))
        parts.append(rep)
        at += len(rep)
        pos = i + 1
    if not cuts:
        return Normalized(text, [])
    parts.append(text[pos:])
    return Normalized("".join(parts), cuts)


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def rrn_checksum_ok(d: str) -> bool:
    """구 체계 검증번호. 2020-10 이후 발급분은 여기서 False가 나오는 게 정상이다."""
    return len(d) == 13 and (11 - _rrn_sum(d) % 11) % 10 == int(d[12])


def frn_checksum_ok(d: str) -> bool:
    """외국인등록번호의 구 체계 검증번호(D-117, Presidio KR_FRN과 같다). 2020-10 이후 발급분은 임의 번호다."""
    return len(d) == 13 and (13 - _rrn_sum(d) % 11) % 10 == int(d[12])


def _rrn_sum(d: str) -> int:
    return sum(int(a) * w for a, w in zip(d[:12], _RRN_WEIGHTS))


def brn_check(d: str) -> int:
    """사업자등록번호 앞 9자리의 검증 숫자 — 1,3,7,1,3,7,1,3,5를 곱한 합에 9번째×5의 십의 자리를 더한다(D-117, Presidio KR_BRN과 같다)."""
    return -(sum(int(a) * w for a, w in zip(d, (1, 3, 7, 1, 3, 7, 1, 3, 5))) + int(d[8]) * 5 // 10) % 10


def crn_check(d: str) -> int:
    """법인등록번호 앞 12자리의 검증 숫자 — 1·2를 번갈아 곱한 합, 자리 나눔 없음(D-117)."""
    return -sum(int(a) * w for a, w in zip(d, (1, 2) * 6)) % 10


def rrn_date_ok(yy: str, mm: str, dd: str, gender: str) -> bool:
    base = _CENTURY.get(gender)
    if base is None:
        return False
    try:
        date(base + int(yy), int(mm), int(dd))
    except ValueError:
        return False
    return True


def card_brand_ok(d: str) -> bool:
    """발급사 범위(IIN)와 길이(D-116). 국내 전용 카드는 첫 자리 9(MII 9 = 국가 지정)다."""
    n, p2, p3, p4 = len(d), int(d[:2]), int(d[:3]), int(d[:4])
    return ((d[0] == "4" and n in (13, 16, 19))                                       # Visa
            or ((51 <= p2 <= 55 or 2221 <= p4 <= 2720) and n == 16)                    # Mastercard
            or (p2 in (34, 37) and n == 15)                                            # Amex
            or (3528 <= p4 <= 3589 and 16 <= n <= 19)                                  # JCB
            or ((p2 in (62, 65) or p4 == 6011 or 644 <= p3 <= 649) and 16 <= n <= 19)  # UnionPay·Discover
            or ((300 <= p3 <= 305 or p2 in (36, 38, 39)) and 14 <= n <= 19)            # Diners
            or (d[0] == "9" and n == 16))                                              # 국내 전용


def _near(context: re.Pattern, text: str, start: int, end: int) -> bool:
    return context.search(text, max(0, start - CONTEXT_CHARS), end + CONTEXT_CHARS) is not None


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
    """겹치지 않는 탐지 결과를 원문 위치 순으로 돌려준다. 찾기는 정규화한 텍스트에서 한다(D-116).

    종류마다 우선순위가 다르고(PRIORITY), 한 종류의 매치는 finditer가 왼쪽부터 겹치지 않게 내놓는다.
    그래서 우선순위 순으로 종류를 돌며 이미 자리 잡은 구간(위치 순)과 두 포인터로 한 번만 비교한다 —
    탐지 건수에 선형이다. 결과는 예전 방식(후보 전체를 우선순위·길이·위치로 정렬해 탐욕적으로 고르기)과 같다.
    2026-10-29 이전에는 후보마다 자리 잡은 구간 전체를 훑어 건수의 제곱으로 느려졌다 — 전화번호 2만 개(273KB)에
    4초, 1MiB에 60초. 워커 1개라 그동안 게이트웨이 전체가 멈춘다(D-102).
    """
    norm = normalize(text)
    by_kind = candidates(norm.text)
    taken: list[Finding] = []
    for kind in sorted(PRIORITY, key=PRIORITY.__getitem__):
        taken = _merge_free(taken, _disjoint(by_kind[kind]))
    if not norm.cuts:
        return taken
    return [Finding(f.kind, *norm.span(f.start, f.end), f.confidence, f.mask) for f in taken]


def candidates(text: str) -> dict[str, list[Finding]]:
    """종류마다 겹침 해소 전의 후보(text 위치 순). text는 정규화한 텍스트다. 종류 안의 겹침(세 전화 패턴)은 `_disjoint`가 고른다."""
    by_kind: dict[str, list[Finding]] = {k: [] for k in PRIORITY}

    for m in SECRET_RE.finditer(text):
        by_kind["secret"].append(Finding("secret", m.start(), m.end(), "strong"))

    for m in RRN_RE.finditer(text):
        yy, mm, dd, gender, tail = m.groups()
        if not rrn_date_ok(yy, mm, dd, gender):
            continue
        d, kind = digits(m.group(0)), "frn" if gender in "5678" else "rrn"
        strong = (frn_checksum_ok if kind == "frn" else rrn_checksum_ok)(d)
        if not strong and m.group(0)[6] == "-" and crn_check(d) == int(d[12]) and _near(CRN_CONTEXT_RE, text, m.start(), m.end()):
            continue          # 주민 꼴 법인등록번호(서울 주식회사 `110111-1…`) — 아래 GROUPED_RE가 crn으로 잡는다(D-117 §2-4)
        # 검증식 실패(2020-10 이후 번호)는 구분자가 있거나 문맥어가 가까울 때만 가린다 — 구분자 없는 13자리는 바코드·송장과 겹친다
        mask = strong or not m.group(0).isdigit() or _near(RRN_CONTEXT_RE, text, m.start(), m.end())
        by_kind[kind].append(Finding(kind, m.start(), m.end(), "strong" if strong else "weak", mask))

    for m in GROUPED_RE.finditer(text):
        groups = m.group(0).split("-")
        layout, d = tuple(map(len, groups)), "".join(groups)
        if layout == (3, 2, 5):
            if brn_check(d) == int(d[9]):
                by_kind["brn"].append(Finding("brn", m.start(), m.end(), "strong"))
        elif layout == (6, 7):
            if crn_check(d) == int(d[12]):
                by_kind["crn"].append(Finding("crn", m.start(), m.end(), "strong"))
        elif layout == (2, 2, 6, 2):
            if d[:2] in DRIVER_REGIONS:
                by_kind["driver"].append(Finding("driver", m.start(), m.end(), "strong"))
        elif layout in ACCOUNT_LAYOUTS:     # 검증식이 없어 묶음 길이뿐 — 계좌 문맥어가 가까울 때만 가린다
            by_kind["account"].append(Finding("account", m.start(), m.end(), "weak",
                                              _near(ACCOUNT_CONTEXT_RE, text, m.start(), m.end())))

    for m in CARD_RE.finditer(text):
        d = digits(m.group(0))
        if 13 <= len(d) <= 19 and luhn_ok(d):
            # 발급사 범위 밖(IMEI·Snowflake·주문번호가 Luhn을 우연히 통과)은 카드 문맥어가 가까울 때만 가린다
            mask = card_brand_ok(d) or _near(CARD_CONTEXT_RE, text, m.start(), m.end())
            by_kind["card"].append(Finding("card", m.start(), m.end(), "strong", mask))

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

    for m in PASSPORT_RE.finditer(text):
        new = not m.group(0)[1:].isdigit()             # 차세대(숫자 사이에 글자)는 늘, 구형(글자 + 8자리)은 문맥어가 있을 때만 가린다
        by_kind["passport"].append(Finding("passport", m.start(), m.end(), "strong" if new else "weak",
                                           new or _near(PASSPORT_CONTEXT_RE, text, m.start(), m.end())))

    for m in IPV4_RE.finditer(text):
        ip = ipaddress.IPv4Address(m.group(0))
        # 공인 주소만 — 사설·예약·멀티캐스트·끝이 0인 망 주소는 개인정보가 아니고, 대체값은 늘 공인 주소라 복원에도 필요 없다
        if ip.is_global and not ip.is_multicast and not m.group(0).endswith(".0"):
            by_kind["ipv4"].append(Finding("ipv4", m.start(), m.end(), "strong",
                                           not _near(VERSION_CONTEXT_RE, text, m.start(), m.end())))
    return by_kind


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
