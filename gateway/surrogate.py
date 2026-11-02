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
  D-126   person·address·org(탐지 사이드카의 NER 종류)는 모양이 없다 — 복원은 볼트가 발급한 문자열을 찾는다(정규식에 다시 걸릴 필요가 없다).
          person  한글이면 성(빈도 가중) + 이름 음절, 길이는 원문과 같되 최소 3자, 마지막 음절의 받침 부류(없음·ㄹ·그 밖)를 원문과 맞춘다 — 뒤따르는 조사(은/는·이/가·으로/로)가
                  가짜 이름에도, 복원한 원문에도 맞는다. 라틴 글자면 영문 이름(토큰 수 유지, 마지막은 성), 그 밖(한자·가나·별명)은 한글 3자.
          address 앞쪽 시·도·시·군·구 토큰은 그대로, 도로(…로·…길)·법정동(…동·읍·면·리)·아파트·건물 이름은 사전에서, 그 밖의 한글 토큰은 같은 길이의 음절로,
                  숫자는 자릿수를 지키고 마지막 자리는 원문 그대로(읽는 소리의 받침이 같아 조사가 맞는다).
          org     알려진 꼬리(은행·병원·학교·공사·(주)·주식회사·Inc.…)는 남기고 줄기를 사전에서 바꾼다.
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


# --- 이름·주소·직장(D-126) — 사전은 모두 합성·일반 명사 조합이다. 성씨 비중은 통계청 분포를 대략 따른다(eval/ner/make_synth.py와 같은 표) ---
SURNAMES = (("김", 215), ("이", 147), ("박", 84), ("최", 47), ("정", 43), ("강", 23), ("조", 21), ("윤", 21), ("장", 20), ("임", 17), ("한", 15),
            ("오", 15), ("서", 14), ("신", 14), ("권", 14), ("황", 14), ("안", 14), ("송", 13), ("전", 11), ("홍", 11), ("유", 11), ("고", 9),
            ("문", 9), ("양", 9), ("손", 9), ("배", 8), ("백", 7), ("허", 6), ("남", 6), ("심", 5), ("노", 4), ("하", 4), ("곽", 4), ("성", 4),
            ("차", 4), ("주", 4), ("우", 4), ("구", 4), ("민", 3), ("류", 3), ("나", 3), ("진", 3), ("지", 3), ("엄", 3), ("채", 3), ("원", 3))
_SURNAME_NAMES = [x for x, _ in SURNAMES]
_SURNAME_WEIGHTS = [w for _, w in SURNAMES]
# 이름 음절을 마지막 글자의 받침 부류로 나눈다 — 조사가 갈리는 셋: 없음(는·가·로)·ㄹ(은·이·로)·그 밖(은·이·으로)
GIVEN_OPEN = tuple("수우아지서유호재주희미비나다리시예하세채태도규기소루이")
GIVEN_RIEUL = tuple("율설별철솔결일열글늘")
GIVEN_CLOSED = tuple("준민현진영성혁빈원석훈경정연은선환찬범섭욱건한윤승종상식")
GIVEN_ANY = GIVEN_OPEN + GIVEN_RIEUL + GIVEN_CLOSED
EN_FIRST = ("James", "Olivia", "Daniel", "Emma", "Michael", "Sophia", "David", "Grace", "Andrew", "Chloe", "Ethan", "Hannah", "Ryan", "Julia", "Kevin", "Laura")
EN_LAST = ("Walker", "Bennett", "Carter", "Hayes", "Morgan", "Foster", "Reed", "Brooks", "Parker", "Collins", "Hughes", "Turner")
SHORT_SIDO = frozenset("서울 부산 대구 인천 광주 대전 울산 세종 경기 강원 충북 충남 전북 전남 경북 경남 제주".split())
# 도로·동·줄기 사전은 실제 도로명·기관명과 겹치지 않게 두 낱말을 붙인 조어다(D-126 리뷰 — '한빛로'·'미르재단'은 실존한다)
ROADS = ("가온누리로", "새솔빛로", "다온별로", "하람달로", "온새미로", "다솜빛로", "라온하늘로", "나래빛로", "이음새로", "바름누리로", "솔아람로", "별가온로")
DONGS = ("가온누리", "새솔빛", "다온별", "하람달", "온새미", "다솜빛", "라온하늘", "나래빛", "이음새", "바름누리")
APT_TAILS = ("아파트", "오피스텔", "빌딩", "타워", "빌라", "맨션", "주공", "타운", "캐슬", "파크")
ORG_PREFIXES = ("(주)", "주식회사", "재단법인", "사단법인", "유한회사")
ORG_TAILS = ("초등학교", "중학교", "고등학교", "대학교병원", "대학병원", "대학교", "대학", "학교", "유치원", "어린이집", "병원", "의원", "치과", "한의원", "약국", "은행", "증권", "보험",
             "카드", "캐피탈", "공사", "공단", "회계법인", "법무법인", "세무법인", "법인", "연구원", "연구소", "재단", "협회", "조합", "물산", "전자", "건설", "통운", "화학", "제약",
             "식품", "자동차", "그룹", "(주)")
EN_ORG_TAILS = ("Inc.", "Inc", "Ltd.", "Ltd", "Corp.", "Corp", "LLC", "Co.", "Systems", "Traders", "Labs", "Partners", "Group", "Holdings")
ORG_STEMS = ("가온누리", "새솔빛", "다온별", "하람달", "온새미", "다솜빛", "라온하늘", "나래빛", "이음새", "바름누리", "솔아람", "별가온")
EN_ORG_STEMS = ("Northstar", "Bluefield", "Silverline", "Oakridge", "Brightwater", "Stonebridge", "Clearview", "Redwood")
HANGUL_RE = re.compile(r"[가-힣]")
HANGUL_WORD_RE = re.compile(r"[가-힣]+")
LATIN_RE = re.compile(r"[A-Za-z]")
DIGIT_RUN_RE = re.compile(r"\d+")
ADDR_HEAD_RE = re.compile(r"^[가-힣]{2,}(?:특별자치시|특별자치도|특별시|광역시|자치구|시|도|군|구)$")
HEAD_PREFIX_RE = re.compile(r"^(?:[가-힣]{1,5}?(?:특별자치시|특별자치도|특별시|광역시|시|도|군|구))*")   # 붙여 쓴 '서울시강남구테헤란로'의 머리
RUN_RE = re.compile(r"[가-힣]+|\d+|[^가-힣\d]+")
PUNCT_RE = re.compile(r"^([^\w가-힣]*)(.*?)([^\w가-힣]*)$", re.S)
UNIT_WORDS = frozenset(("동", "호", "층", "번지", "번길", "번", "가", "길", "로", "차", "단지", "호실", "라인", "출구", "지하"))   # 숫자에 붙는 단위 — 그대로 둔다


def final_class(c: str) -> str:
    """한글 음절 하나의 받침 부류 — ''(없음)·'ㄹ'·'ㅇ'(그 밖). 한글이 아니면 그 밖으로 본다."""
    code = ord(c) - 0xAC00
    if not 0 <= code <= 11171:
        return "ㅇ"
    jong = code % 28
    return "" if jong == 0 else "ㄹ" if jong == 8 else "ㅇ"


def _korean_name(n: int, last_class: str, rng: random.Random) -> str:
    pool = {"": GIVEN_OPEN, "ㄹ": GIVEN_RIEUL}.get(last_class, GIVEN_CLOSED)
    body = [rng.choice(GIVEN_ANY) for _ in range(n - 2)] + [rng.choice(pool)]
    return rng.choices(_SURNAME_NAMES, _SURNAME_WEIGHTS)[0] + "".join(body)


def person(value: str, rng: random.Random) -> str:
    stripped = value.strip()
    if LATIN_RE.search(stripped) and not HANGUL_RE.search(stripped):
        tokens = stripped.split()
        out = [rng.choice(EN_FIRST) for _ in tokens[:-1]] + [rng.choice(EN_LAST if len(tokens) > 1 else EN_FIRST)]
        name = " ".join(out)
        return name.upper() if stripped.isupper() else name.lower() if stripped.islower() else name
    n = max(3, len(stripped)) if HANGUL_RE.fullmatch(stripped[-1:]) else 3
    name = _korean_name(n, final_class(stripped[-1]), rng)
    return name if name != stripped else _korean_name(n, final_class(stripped[-1]), rng)


def _digits_keep_last(token: str, rng: random.Random) -> str:
    """숫자 묶음마다 자릿수를 지키고 마지막 자리는 그대로 — 읽는 소리의 받침이 같아 조사가 맞는다."""
    return DIGIT_RUN_RE.sub(lambda m: "".join(rng.choice(string.digits) for _ in m.group(0)[:-1]) + m.group(0)[-1], token)


def _syllables(n: int, rng: random.Random) -> str:
    return "".join(rng.choice(GIVEN_ANY) for _ in range(n))


def _hangul_part(run: str, rng: random.Random) -> str:
    """주소 토큰 속 한글 덩어리 하나 — 시·도·시·군·구 머리는 그대로, 단위 낱말(동·호·층·번길…)은 그대로, 도로·동·아파트 꼬리는 사전, 그 밖은 같은 길이의 음절."""
    if run in UNIT_WORDS:
        return run
    head = HEAD_PREFIX_RE.match(run).group(0)      # type: ignore[union-attr]
    rest = run[len(head):]
    if not rest:
        return run
    for tail in APT_TAILS:
        if rest.endswith(tail) and len(rest) > len(tail):
            return head + rng.choice(DONGS) + tail
    if len(rest) >= 2 and rest.endswith(("로", "길")):
        road = rng.choice(ROADS)
        return head + (road if rest.endswith("로") else road[:-1] + "길")
    if len(rest) >= 2 and rest.endswith(("동", "읍", "면", "리", "가")):
        return head + rng.choice(DONGS) + rest[-1]
    return head + _syllables(len(rest), rng)


def _address_token(core: str, rng: random.Random) -> str:
    """토큰을 한글·숫자·그 밖의 덩어리로 나눠 각각 바꾼다 — '테헤란로123'·'역삼1동'·'삼성아파트101동'처럼 붙여 쓴 토큰에서도 한글이 남지 않는다(D-126 리뷰).
    숫자는 자릿수와 마지막 자리를 지키고, 라틴 글자는 같은 부류의 무작위, 구두점은 그대로."""
    out: list[str] = []
    for m in RUN_RE.finditer(core):
        s = m.group(0)
        if s.isdigit():
            out.append(_digits_keep_last(s, rng))
        elif "가" <= s[0] <= "힣":
            out.append(_hangul_part(s, rng))
        else:
            out.append(_scramble(s, rng))
    return "".join(out)


def address(value: str, rng: random.Random) -> str:
    parts = re.split(r"(\s+)", value)
    out: list[str] = []
    head = True
    for part in parts:
        if not part or part.isspace():
            out.append(part)
            continue
        lead, core, trail = PUNCT_RE.match(part).groups()      # type: ignore[union-attr]  # '(세종로)'의 괄호
        if head and (core in SHORT_SIDO or ADDR_HEAD_RE.match(core)):
            out.append(part)
            continue
        head = False
        out.append(lead + _address_token(core, rng) + trail)
    made = "".join(out)
    if made == value:                                          # 바꿀 토큰이 숫자 한 자리뿐일 때 — 그 자리도 바꾼다
        made = DIGIT_RUN_RE.sub(lambda m: "".join(rng.choice(string.digits) for _ in m.group(0)), value)
    return made


def org(value: str, rng: random.Random) -> str:
    stripped = value.strip()
    if LATIN_RE.search(stripped) and not HANGUL_RE.search(stripped):
        tokens = stripped.split()
        if len(tokens) > 1 and tokens[-1] in EN_ORG_TAILS:
            return " ".join([rng.choice(EN_ORG_STEMS) for _ in tokens[:-1]] + [tokens[-1]])
        return " ".join(rng.choice(EN_ORG_STEMS) for _ in tokens)
    prefix = next((p for p in ORG_PREFIXES if stripped.startswith(p)), "")
    body = stripped[len(prefix):].lstrip()
    gap = " " if prefix and stripped[len(prefix):len(prefix) + 1] == " " else ""
    tail = next((t for t in ORG_TAILS if body.endswith(t) and len(body) > len(t)), "")
    stem = body[:len(body) - len(tail)].rstrip()
    return prefix + gap + _org_stem(stem, rng) + tail


def _org_stem(stem: str, rng: random.Random) -> str:
    """줄기의 한글 덩어리는 사전(첫 덩어리)·같은 길이의 음절(그 뒤), 라틴·숫자는 같은 부류의 무작위 — 'SK하이닉스'의 한글이 남지 않는다(D-126 리뷰)."""
    out: list[str] = []
    first = True
    for m in RUN_RE.finditer(stem):
        s = m.group(0)
        if "가" <= s[0] <= "힣":
            out.append(rng.choice(ORG_STEMS) if first else _syllables(len(s), rng))
            first = False
        else:
            out.append(_scramble(s, rng))
    return "".join(out) or rng.choice(ORG_STEMS)


MAKERS = {"phone": phone, "card": card, "rrn": rrn, "email": email, "secret": secret, "frn": frn, "crn": crn, "brn": brn,
          "driver": driver, "account": account, "passport": passport, "ipv4": ipv4, "person": person, "address": address, "org": org}


def make(kind: str, value: str, rng: random.Random | None = None) -> str:
    return MAKERS[kind](value, rng or _SYSTEM)
