#!/usr/bin/env python3
"""PII 평가 코퍼스 생성기(D-115, PLAN 8단계). 시드 고정·합성 값만·표준 라이브러리만.

  python3 eval/pii/make_corpus.py     # corpus.jsonl·hard.jsonl을 다시 쓴다 — 같은 코드면 바이트까지 같다(tests/test_pii_corpus.py)

corpus.jsonl  양성 500(종류마다 100, 문장 하나에 값 하나) + 음성 1,000(숫자가 빽빽한 업무 문장 10묶음 × 100, 개인정보 없음).
hard.jsonl    손으로 고른 어려운 사례. 지금 탐지가 틀리는 꼴도 일부러 넣었다 — 게이트에 넣지 않는다.
한 줄: {"id", "set": "pos"|"neg", "group", "text", "spans": [{"kind", "start", "end"}]} + 양성은 "ctx"(값 옆에 그 종류를 가리키는 말이 있는가),
hard는 "note". 양성 꼴은 탐지 정규식이 아니라 실제 번호 체계(발급사 범위·지역번호·키 형식)에서 골랐다.
"""
from __future__ import annotations

import base64
import json
import random
import string
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261030
D = string.digits
ALNUM = string.ascii_letters + string.digits
B64URL = ALNUM + "-_"
UPPER_D = string.ascii_uppercase + string.digits
HEX = "0123456789abcdef"


def rand(r: random.Random, chars: str, n: int) -> str:
    return "".join(r.choice(chars) for _ in range(n))


def num(r: random.Random, n: int, first: str = "123456789") -> str:
    """n자리 숫자. 앞자리가 0이 아니다 — 0으로 시작하는 숫자열은 전화번호 꼴과 겹친다."""
    return r.choice(first) + rand(r, D, n - 1)


def luhn_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return str(-total % 10)


# --- 양성 ---------------------------------------------------------------------
RRN_W = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)


def rrn(r: random.Random, valid: bool) -> str:
    """내국인 주민번호 13자리. 성별 자리 1~4, 날짜는 실제 있는 날. valid면 구 체계 검증식을 맞추고, 아니면 일부러 어긋낸다(2020-10 이후 번호)."""
    year = r.randrange(1940, 2024)
    head = f"{year % 100:02d}{r.randrange(1, 13):02d}{r.randrange(1, 29):02d}{r.choice('12' if year < 2000 else '34')}{rand(r, D, 5)}"
    check = (11 - sum(int(a) * w for a, w in zip(head, RRN_W)) % 11) % 10
    return head + str(check if valid else (check + r.randrange(1, 10)) % 10)


def rrn_value(r: random.Random) -> tuple[str, str]:
    valid = r.random() < 0.5
    d, fmt = rrn(r, valid), r.choices(("hyphen", "nosep", "space"), (60, 25, 15))[0]
    sep = {"hyphen": "-", "nosep": "", "space": " "}[fmt]
    return f"{'ok' if valid else 'fail'}-{fmt}", d[:6] + sep + d[6:]


CARD_BRANDS = (  # (이름, 길이, 접두사)
    ("visa", 16, lambda r: "4"),
    ("master", 16, lambda r: str(r.randrange(51, 56)) if r.random() < 0.7 else str(r.randrange(2221, 2721))),
    ("amex", 15, lambda r: r.choice(("34", "37"))),
    ("jcb", 16, lambda r: str(r.randrange(3528, 3590))),
    ("unionpay", 16, lambda r: "62"),
)


def card_value(r: random.Random) -> tuple[str, str]:
    name, length, prefix = r.choices(CARD_BRANDS, (30, 30, 15, 15, 10))[0]
    body = prefix(r)
    body += rand(r, D, length - len(body) - 1)
    d = body + luhn_digit(body)
    fmt = r.choices(("hyphen", "space", "nosep"), (50, 20, 30))[0]
    parts = (d[:4], d[4:10], d[10:]) if length == 15 else (d[:4], d[4:8], d[8:12], d[12:])
    return f"{name}-{fmt}", {"hyphen": "-", "space": " ", "nosep": ""}[fmt].join(parts)


AREA = ("031", "032", "033", "041", "042", "043", "044", "051", "052", "053", "054", "055", "061", "062", "063", "064")


def mid(r: random.Random) -> str:
    return str(r.randrange(200, 1000)) if r.random() < 0.3 else str(r.randrange(2000, 10000))


def last4(r: random.Random) -> str:
    return f"{r.randrange(10000):04d}"


PHONE_GROUPS = (  # (묶음, 비중, 만들기)
    ("mobile-hyphen", 25, lambda r: f"010-{r.randrange(2000, 10000)}-{last4(r)}"),
    ("mobile-nosep", 10, lambda r: f"010{r.randrange(2000, 10000)}{last4(r)}"),
    ("mobile-dot", 5, lambda r: f"010.{r.randrange(2000, 10000)}.{last4(r)}"),
    ("mobile-space", 5, lambda r: f"010 {r.randrange(2000, 10000)} {last4(r)}"),
    ("mobile-legacy", 5, lambda r: f"{r.choice(('011', '016', '017', '019'))}-{r.randrange(200, 1000)}-{last4(r)}"),
    ("seoul", 10, lambda r: f"02-{mid(r)}-{last4(r)}"),
    ("regional", 15, lambda r: f"{r.choice(AREA)}-{mid(r)}-{last4(r)}"),
    ("paren", 5, lambda r: f"({r.choice(('02',) + AREA)}) {mid(r)}-{last4(r)}"),
    ("intl-kr", 10, lambda r: r.choice((lambda: f"+82-10-{r.randrange(2000, 10000)}-{last4(r)}",
                                        lambda: f"+82 10 {r.randrange(2000, 10000)} {last4(r)}",
                                        lambda: f"+82-2-{mid(r)}-{last4(r)}"))()),
    ("intl-other", 5, lambda r: r.choice((lambda: f"+1 202 555 01{r.randrange(100):02d}",
                                          lambda: f"+81 3 {last4(r)} {last4(r)}",
                                          lambda: f"+44 20 {last4(r)} {last4(r)}"))()),
    ("voip-070", 5, lambda r: f"070-{r.randrange(2000, 10000)}-{last4(r)}"),
)

GIVEN = ("minji", "seojun", "jiwoo", "hayun", "dohyun", "yerin", "junho", "subin", "taeyang", "eunji", "sangwoo", "nari",
         "hyunwoo", "dahye", "jaemin", "sora")
FAMILY = ("kim", "lee", "park", "choi", "jung", "kang", "cho", "yoon", "jang", "lim", "han", "oh", "seo", "shin")
MAIL_DOMAINS = ("example.com", "example.net", "example.org", "mail.example", "corp.example")
EMAIL_GROUPS = (
    ("dot", 30, lambda r: f"{r.choice(GIVEN)}.{r.choice(FAMILY)}@{r.choice(MAIL_DOMAINS)}"),
    ("underscore-hyphen", 15, lambda r: f"{r.choice(GIVEN)}{r.choice('_-')}{r.choice(FAMILY)}@{r.choice(MAIL_DOMAINS)}"),
    ("digits", 15, lambda r: f"{r.choice(FAMILY)}{r.choice(GIVEN)}{r.randrange(70, 100)}@{r.choice(MAIL_DOMAINS)}"),
    ("plus", 10, lambda r: f"{r.choice(GIVEN)}+{r.choice(('orders', 'news', 'hr', 'billing'))}@{r.choice(MAIL_DOMAINS)}"),
    ("upper", 10, lambda r: f"{r.choice(GIVEN).capitalize()}.{r.choice(FAMILY).upper()}@{r.choice(MAIL_DOMAINS).upper()}"),
    ("subdomain", 20, lambda r: f"{r.choice(GIVEN)}.{r.choice(FAMILY)}@{r.choice(('hr', 'dev', 'sales', 'kr'))}.{r.choice(MAIL_DOMAINS)}"),
)
JWT_HEAD = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()


def jwt(r: random.Random) -> str:
    claims = json.dumps({"sub": rand(r, D, 8), "iat": 1761800000 + r.randrange(10**6)}, separators=(",", ":"))
    return f"{JWT_HEAD}.{base64.urlsafe_b64encode(claims.encode()).rstrip(b'=').decode()}.{rand(r, B64URL, 43)}"


def pem(r: random.Random) -> str:
    kind = r.choice(("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY"))
    body = "\n".join(rand(r, ALNUM + "+/", 64) for _ in range(r.randrange(3, 7)))
    return f"-----BEGIN {kind}-----\n{body}\n-----END {kind}-----"


def slack(r: random.Random) -> str:
    """Slack 토큰 꼴. 실제 봇 토큰 형식(`xoxb-` + 숫자 12 + 숫자 13 + 영숫자 24)을 6자 묶음으로 다시 자른다 — 진짜 형식과 일부러 달라야
    저장소 비밀 검사(GitHub push protection)가 커밋을 막지 않는다(2026-10-30에 8건이 막혔다). 우리 패턴 `xox?-[A-Za-z0-9-]{10,}`에는 그대로 걸린다.
    난수는 예전과 같은 순서·같은 수로 뽑는다 — 다른 줄은 바이트까지 그대로다."""
    body = f"{num(r, 12)}{num(r, 13)}{rand(r, ALNUM, 24)}"
    return "xoxb-" + "-".join(body[i:i + 6] for i in range(0, len(body), 6))


SECRET_GROUPS = (
    ("openai", 15, lambda r: f"sk-proj-{rand(r, B64URL, r.randrange(48, 157))}"),
    ("anthropic", 15, lambda r: f"sk-ant-api03-{rand(r, B64URL, 93)}AA"),
    ("aws", 15, lambda r: f"{r.choice(('AKIA', 'ASIA'))}{rand(r, UPPER_D, 16)}"),
    ("github", 15, lambda r: f"ghp_{rand(r, ALNUM, 36)}" if r.random() < 0.6 else f"github_pat_{rand(r, ALNUM, 22)}_{rand(r, ALNUM, 59)}"),
    ("google", 10, lambda r: f"AIza{rand(r, B64URL, 35)}"),
    ("slack", 10, slack),
    ("jwt", 10, jwt),
    ("pem", 10, pem),
)


def weighted(groups: tuple):
    def pick(r: random.Random) -> tuple[str, str]:
        name, _, make = r.choices(groups, [w for _, w, _ in groups])[0]
        return name, make(r)
    return pick


# 문맥 틀: (문장, 값 옆에 그 종류를 가리키는 말이 있는가). {v} 자리에 값이 들어간다.
TEMPLATES = {
    "rrn": (("고객 주민등록번호는 {v}입니다.", True), ("주민번호: {v} (본인 확인 완료)", True),
            ("{v} — 주민등록번호 뒷자리까지 확인 부탁드립니다.", True), ("가입 신청서의 주민번호 {v}를 전산에 입력했습니다.", True),
            ("생년월일과 등록번호 {v} 대조 결과 일치합니다.", True), ("[본인확인] 주민등록번호 {v}", True),
            ("신청인 정보 {v} / 서울 마포구", False), ("다음 번호로 조회해 주세요: {v}", False),
            ("회원 메모 — {v}, 연락 요망", False), ("{v} 건은 내일 처리합니다.", False)),
    "card": (("결제 카드 {v}로 승인 요청합니다.", True), ("카드번호: {v}", True), ("고객이 불러준 카드 번호는 {v}입니다.", True),
             ("{v} 카드 분실 신고 접수", True), ("환불은 {v} 카드로 진행해 주세요.", True), ("card_number={v}", True),
             ('{"card": "{v}", "amount": 39000}', True), ("결제 실패: {v} (한도 초과)", False),
             ("다음 번호로 다시 시도해 주세요 {v}", False), ("메모: {v}", False)),
    "phone": (("연락처는 {v}입니다.", True), ("{v}로 문자 부탁드립니다.", False), ("담당자 휴대폰 {v}, 부재 시 메일로 주세요.", True),
              ("회신 번호: {v}", True), ("전화번호({v})로 연락 주세요.", True), ("Tel. {v}", True), ('"phone": "{v}"', True),
              ("배송 기사님이 {v}에서 전화를 주셨어요.", False), ("{v}", False), ("확인 후 {v} 쪽으로 다시 걸어 주세요.", False)),
    "email": (("메일은 {v}로 보내 주세요.", True), ("담당자: 김민지 <{v}>", False), ("회신 주소({v})를 확인해 주세요.", True),
              ("From: {v}", True), ("mailto:{v}", True), ("{v} 계정의 비밀번호 초기화 요청", False), ('"email": "{v}"', True),
              ("참조에 {v}도 넣어 주세요.", False), ("견적서는 {v} 앞으로 부탁드립니다.", False), ("ID는 {v}입니다.", False)),
    "secret": (("OPENAI_API_KEY={v}", True), ('api_key = "{v}"', True), ("이 키 {v} 로 호출하면 401이 나요.", True),
               ("토큰: {v}", True), ('{"token": "{v}"}', True), ("Authorization: Bearer {v}", True),
               ("{v}\n이 값이 맞나요?", False), ("설정 파일에 {v} 넣었는데 안 돼요", False)),
    "pem": (("개인 키입니다:\n{v}\n서버에 넣어 주세요.", True), ("{v}", False), ("배포 키 붙여 넣습니다\n\n{v}\n\n확인 부탁해요", True)),
}
VALUES = {"rrn": rrn_value, "card": card_value, "phone": weighted(PHONE_GROUPS), "email": weighted(EMAIL_GROUPS),
          "secret": weighted(SECRET_GROUPS)}


def put(template: str, value: str) -> tuple[str, int, int]:
    start = template.index("{v}")
    return template.replace("{v}", value, 1), start, start + len(value)


def positives(r: random.Random) -> list[dict]:
    out = []
    for kind, make in VALUES.items():
        for i in range(1, 101):
            sub, value = make(r)
            template, ctx = r.choice(TEMPLATES["pem" if sub == "pem" else kind])
            text, start, end = put(template, value)
            out.append({"id": f"pos-{kind}-{i:03d}", "set": "pos", "group": f"{kind}/{sub}", "text": text,
                        "spans": [{"kind": kind, "start": start, "end": end}], "ctx": ctx})
    return out


# --- 음성: 개인정보가 없는 숫자 많은 업무 문장 --------------------------------------
def ymd(r: random.Random) -> str:
    return f"2026{r.randrange(1, 13):02d}{r.randrange(1, 29):02d}"


def hms(r: random.Random) -> str:
    return f"{r.randrange(24):02d}:{r.randrange(60):02d}:{r.randrange(60):02d}"


def ean13(r: random.Random) -> str:
    body = "880" + rand(r, D, 9)
    return body + str(-sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body)) % 10)


def imei(r: random.Random) -> str:
    body = r.choice(("35", "86", "99")) + rand(r, D, 12)
    return body + luhn_digit(body)


def ver(r: random.Random) -> str:
    return f"{r.randrange(0, 4)}.{r.randrange(0, 30)}.{r.randrange(0, 20)}"


CENTER = ("1588", "1577", "1544", "1600", "1644", "1661", "1899")
NEGATIVES = {
    "order": (lambda r: f"주문번호 {ymd(r)}{rand(r, D, r.randrange(5, 9))} 건 배송 문의드립니다.",
              lambda r: f"주문 ORD-{ymd(r)}-{rand(r, D, 6)} 취소 요청이 들어왔습니다.",
              lambda r: f"바코드 {ean13(r)} 상품 재고 확인 부탁드립니다.",
              lambda r: f"상품코드 SKU-{num(r, 5)}-KR, 수량 {r.randrange(1, 50)}개",
              lambda r: f"쿠폰 번호 {num(r, 4)}-{rand(r, D, 4)}-{rand(r, D, 4)}-{rand(r, D, 4)} 사용 처리했습니다.",
              lambda r: f"주문 {num(r, 13)}의 결제 금액이 맞지 않아요."),
    "tracking": (lambda r: f"CJ대한통운 송장번호 {num(r, 12, '56')} 조회해 주세요.",
                 lambda r: f"우체국 등기 {num(r, 13)} 배송 중입니다.",
                 lambda r: f"롯데택배 {num(r, 4)}-{rand(r, D, 4)}-{rand(r, D, 4)} 오늘 도착 예정",
                 lambda r: f"한진택배 운송장 {num(r, r.randrange(10, 13))} 반송 처리",
                 lambda r: f"송장 {num(r, 12)} / {num(r, 12)} 두 건 묶음 배송"),
    "timestamp": (lambda r: f"2026-{r.randrange(1, 13):02d}-{r.randrange(1, 29):02d}T{hms(r)}+09:00에 결제가 완료됐습니다.",
                  lambda r: f"created_at={1761800000 + r.randrange(10**7)} updated_at={1761800000 + r.randrange(10**7)}",
                  lambda r: f"ts={1761800000000 + r.randrange(10**10)} 이벤트 수신",
                  lambda r: f"로그 시각 {ymd(r)}{hms(r).replace(':', '')} 기준 집계",
                  lambda r: f"2026.{r.randrange(1, 13):02d}.{r.randrange(1, 29):02d} {hms(r)[:5]} 접수"),
    "snowflake": (lambda r: f"메시지 ID {num(r, r.randrange(18, 20))} 삭제 요청",
                  lambda r: f"discord user_id={num(r, 18)}",
                  lambda r: f"tweet_id: {num(r, 19)}",
                  lambda r: f"거래 ID {num(r, 19)} 정산 대기"),
    "imei": (lambda r: f"단말 IMEI {imei(r)} 개통 문의",
             lambda r: (lambda d: f"IMEI: {d[:2]}-{d[2:8]}-{d[8:14]}-{d[14]}")(imei(r)),
             lambda r: f"기기 정보 IMEI1 {imei(r)} / IMEI2 {imei(r)}",
             lambda r: f"분실 단말 일련번호 {imei(r)} 조회"),
    "diff": (lambda r: (lambda a, b: f"@@ -{a},{b} +{a + r.randrange(9)},{b + r.randrange(5)} @@ def handler(request):")(
                 r.randrange(1, 20000), r.randrange(3, 20)),
             lambda r: f"-    retries = {r.randrange(1, 10)}",
             lambda r: f"+    timeout_ms = {r.randrange(1000, 120000)}",
             lambda r: f"index {rand(r, HEX, 7)}..{rand(r, HEX, 7)} 100644",
             lambda r: f"+    MAX_ROWS = {r.randrange(10**5, 10**8)}",
             lambda r: f"diff --git a/app/service_{r.randrange(100)}.py b/app/service_{r.randrange(100)}.py"),
    "log": (lambda r: f"2026-10-30 {hms(r)},{r.randrange(1000):03d} INFO [worker-{r.randrange(1, 9)}] request_id={rand(r, HEX, 8)} "
                      f"latency_ms={r.randrange(3, 5000)} status=200 bytes={r.randrange(100, 10**6)}",
            lambda r: f"GET /api/v1/orders/{num(r, r.randrange(13, 17))} 200 {r.randrange(3, 900)}ms",
            lambda r: f"pid={num(r, 5)} port={r.randrange(1024, 65536)} conn={r.randrange(1, 500)}",
            lambda r: f"WARN retry {r.randrange(1, 6)}/5 after {r.randrange(100, 9000)}ms (attempt_id={num(r, 10)})"),
    "version": (lambda r: f"v{ver(r)} 배포 완료",
                lambda r: f"fastapi=={ver(r)}",
                lambda r: f"User-Agent: Mozilla/5.0 Chrome/{130 + r.randrange(10)}.0.{num(r, 4)}.{r.randrange(10, 200)}",
                lambda r: f"build {ymd(r)}.{r.randrange(1, 20)}",
                lambda r: f"Android {r.randrange(10, 16)} (API {r.randrange(29, 36)}) 앱 버전 {ver(r)} ({num(r, 6)})"),
    "extension": (lambda r: f"내선 {num(r, 4)}로 돌려 드리겠습니다.",
                  lambda r: f"대표번호 {r.choice(CENTER)}-{rand(r, D, 4)}",
                  lambda r: f"고객센터 {r.choice(CENTER)}-{rand(r, D, 4)} (평일 9시~18시)",
                  lambda r: f"팩스는 내선 {num(r, 4)}번 옆 복합기로 보내 주세요.",
                  lambda r: f"회의실 예약은 내선 {num(r, 3)}, 급한 건 {num(r, 4)}번"),
    "money": (lambda r: f"결제 금액 {r.randrange(1000, 10**7):,}원",
              lambda r: f"2026년 {r.randrange(1, 13)}월 {r.randrange(1, 29)}일 {r.randrange(9, 19)}시 정산 예정",
              lambda r: f"부가세 포함 합계 ₩{r.randrange(10**4, 10**8):,}",
              lambda r: f"수량 {r.randrange(1, 500)}개, 단가 {r.randrange(100, 10**6):,}원",
              lambda r: (lambda m: f"기간 2026.{m:02d}.01~2026.{m:02d}.28, 누적 {r.randrange(10**5, 10**9):,}원")(r.randrange(1, 13))),
}


def negatives(r: random.Random) -> list[dict]:
    return [{"id": f"neg-{group}-{i:03d}", "set": "neg", "group": group, "text": r.choice(makers)(r), "spans": []}
            for group, makers in NEGATIVES.items() for i in range(1, 101)]


# --- 어려운 사례(손으로 고름) ---------------------------------------------------------
# (양성의 종류 또는 None=음성, 문장, 값(양성만), 메모)
HARD = (
    ("phone", "연락처 ０１０－２３４５－６７８９ 로 주세요", "０１０－２３４５－６７８９", "전각 숫자·하이픈 — 정규화 없음(9단계)"),
    ("phone", "010​-2345-6789로 연락 바랍니다", "010​-2345-6789", "제로폭 공백(9단계)"),
    ("phone", "휴대폰 010–2345–6789", "010–2345–6789", "en 대시 구분자(9단계)"),
    ("phone", "TEL010-2345-6789", "010-2345-6789", "영문자에 붙은 번호 — 앞 글자 경계"),
    ("phone", "+82 (0)10-2345-6789 로 국제전화", "+82 (0)10-2345-6789", "국제 표기의 (0)"),
    ("phone", "연락처: 010-2345-6789.", "010-2345-6789", "문장 끝 마침표(지금도 잡는다)"),
    ("rrn", "주민번호 900101–1234568", "900101–1234568", "en 대시(9단계)"),
    ("rrn", "주민등록번호 900101 - 1234568", "900101 - 1234568", "하이픈 앞뒤 공백"),
    ("rrn", "주민등록번호는 ９００１０１－１２３４５６８ 입니다", "９００１０１－１２３４５６８", "전각(9단계)"),
    ("rrn", "주민등록번호9001011234568", "9001011234568", "한글에 붙은 13자리"),
    ("card", "카드 4111.1111.1111.1111 로 결제", "4111.1111.1111.1111", "점 구분자"),
    ("card", "카드번호 4111 1111 1111 1111", "4111 1111 1111 1111", "공백 구분(지금도 잡는다)"),
    ("card", "카드 ４１１１－１１１１－１１１１－１１１１", "４１１１－１１１１－１１１１－１１１１", "전각(9단계)"),
    ("email", "메일 minji.kim＠example.com 으로", "minji.kim＠example.com", "전각 @(9단계)"),
    ("email", "MINJI.KIM@EXAMPLE.COM 으로 회신", "MINJI.KIM@EXAMPLE.COM", "대문자(지금도 잡는다)"),
    ("email", "minji.kim@example.com이 담당자입니다", "minji.kim@example.com", "조사가 붙은 주소(지금도 잡는다)"),
    ("secret", "키는 sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd 입니다", "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd",
     "OpenAI 키(지금도 잡는다)"),
    (None, "단말 IMEI 490154203237518 개통", None, "Luhn을 통과하는 15자리 — 카드로 오인(9단계 발급사 범위)"),
    (None, "바코드 8801234567893 재고", None, "EAN-13 바코드"),
    (None, "ts=1761812525123 이벤트", None, "밀리초 타임스탬프 13자리"),
    (None, "git@github.com:example/repo.git 에서 받으세요", None, "SSH 원격 주소 — 이메일 꼴"),
    (None, "sk-learn-compatible-pipeline-v2 패키지를 씁니다", None, "sk-로 시작하는 낱말 — 자격 증명 꼴"),
    (None, "주문 231001-1234567 확인 부탁드립니다", None, "날짜-일련번호 주문번호 — 주민번호 꼴(9단계 문맥어)"),
    (None, "대표번호 1588-1234로 전화 주세요", None, "대표번호(지금도 안 잡는다)"),
    (None, "버전 2.10.1234 배포", None, "점이 든 버전"),
    (None, "좌표 37.5665, 126.9780 근처", None, "좌표"),
    (None, "사번 20231234, 학번 2019123456", None, "사번·학번"),
)


def hard() -> list[dict]:
    out = []
    for i, (kind, text, value, note) in enumerate(HARD, 1):
        if kind:
            start = text.index(value)
            item = {"id": f"hard-pos-{i:02d}", "set": "pos", "group": f"{kind}/hard", "text": text,
                    "spans": [{"kind": kind, "start": start, "end": start + len(value)}], "ctx": True, "note": note}
        else:
            item = {"id": f"hard-neg-{i:02d}", "set": "neg", "group": "hard", "text": text, "spans": [], "note": note}
        out.append(item)
    return out


def dumps(items: list[dict]) -> str:
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items)


def render() -> tuple[str, str]:
    """(corpus.jsonl, hard.jsonl) 내용. 같은 코드·같은 시드면 같은 바이트다."""
    r = random.Random(SEED)
    items = positives(r) + negatives(r)
    assert sum(x["set"] == "pos" for x in items) == 500 and sum(x["set"] == "neg" for x in items) == 1000
    return dumps(items), dumps(hard())


if __name__ == "__main__":
    corpus, hard_cases = render()
    (HERE / "corpus.jsonl").write_text(corpus, encoding="utf-8")
    (HERE / "hard.jsonl").write_text(hard_cases, encoding="utf-8")
    print(f"corpus.jsonl {corpus.count(chr(10))}줄, hard.jsonl {hard_cases.count(chr(10))}줄")
