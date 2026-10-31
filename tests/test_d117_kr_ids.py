"""D-117(PLAN 10단계): 한국 식별자 확장 — 외국인등록번호·여권·운전면허·사업자·법인·계좌·IPv4, 070. 데이터는 전부 합성이다.

검증 숫자는 손으로 계산해 적었다: 사업자 123-45-6789 → 1, 법인 134511-001234 → 0, 법인 110111-123456 → 9, 외국인 900101-523456 → 1.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import random
import time
from pathlib import Path

import httpx
import pytest

from gateway import surrogate
from gateway.detectors.base import Action, Inspection
from gateway.detectors.patterns import (
    ACCOUNT_LAYOUTS, DRIVER_REGIONS, brn_check, crn_check, digits, find_all, frn_checksum_ok, rrn_checksum_ok, rrn_date_ok)
from gateway.detectors.pii import PIIDetector
from gateway.streaming import ChatShape, StreamRestorer
from gateway.vault import TokenVault
from tests.test_streaming import content_of, sse

CHAT = "/v1/chat/completions"
FRN = "900101-5234561"            # 검증식 통과
FRN_WEAK = "900101-5234567"
BRN = "123-45-67891"
CRN = "134511-0012340"            # 앞 6자리가 날짜가 아니다 — 주민 꼴이 아닌 법인번호
CRN_RRN_SHAPE = "110111-1234569"  # 1911-01-11·성별 1 — 주민 꼴 법인번호(주민 검증식은 맞지 않는다)
DRIVER = "11-20-123456-78"
ACCOUNT = "110-123-456789"
PASSPORT_OLD, PASSPORT_NEW = "M12345678", "M123A4567"
IP = "121.134.5.6"
VOIP = "070-1234-5678"
SAMPLES = {"frn": [FRN, FRN_WEAK, "9001015234561", "900101 5234561", "050505-7123456"],
           "brn": [BRN], "crn": [CRN, CRN_RRN_SHAPE], "driver": [DRIVER, "28-99-000001-01"],
           "account": [ACCOUNT, "3333-01-1234567", "123456-01-123456", "301-1234-5678-91", "1000-1234-5678"],
           "passport": [PASSPORT_OLD, PASSPORT_NEW, "S00012345", "D987Z6543"], "ipv4": [IP, "1.1.1.1", "100.128.0.1"],
           "phone": [VOIP, "070 1234 5678", "(070) 123-4567"]}


def chat_insp(text: str, session: str = "s") -> Inspection:
    body = json.dumps({"model": "m", "messages": [{"role": "user", "content": text}]}, ensure_ascii=False).encode()
    return Inspection(request_id="r", method="POST", path=CHAT, headers={}, body=body, session=session)


def reply(text: str) -> str:
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}, ensure_ascii=False)


def found(text: str) -> list[tuple[str, str]]:
    return [(f.kind, text[f.start:f.end]) for f in find_all(text)]


# ---------- K1 탐지 ----------

@pytest.mark.parametrize("text, kind, value", [
    (f"외국인등록번호 {FRN} 확인", "frn", FRN),
    (f"사업자등록번호 {BRN}", "brn", BRN),
    (f"법인등록번호 {CRN}", "crn", CRN),
    (f"운전면허 {DRIVER} 갱신", "driver", DRIVER),
    (f"계좌 {ACCOUNT}로 입금", "account", ACCOUNT),
    (f"여권 {PASSPORT_OLD}", "passport", PASSPORT_OLD),
    (f"{PASSPORT_NEW} 탑승", "passport", PASSPORT_NEW),
    (f"접속 {IP}에서 로그인", "ipv4", IP),
    (f"http://{IP}:8080/health", "ipv4", IP),
    (f"ssh admin@{IP}", "ipv4", IP),
    (f"인터넷 전화 {VOIP}", "phone", VOIP),
])
def test_k1_each_new_kind_is_found_with_the_whole_value(text, kind, value):
    assert found(text) == [(kind, value)]


@pytest.mark.parametrize("text", [
    "사업자 123-45-67890",                 # 검증식 실패
    "법인 134511-0012341",                 # 검증식 실패
    "면허 10-20-123456-78", "면허 27-20-123456-78",   # 없는 지역
    "번호 110-1234-56789",                 # 은행 꼴 아님(3-4-5)
    "번호 1-2-3-4-5-6",                    # 묶음이 너무 많다
    "여권 A12345678", "여권 M1234567", "여권 M123456789", "SM12345678", "M12345678X",
    "외국인 900101-9234567", "외국인 901301-5234561",  # 성별 9, 13월
    "192.168.0.1", "10.0.0.1", "127.0.0.1", "172.20.1.1", "100.64.1.1",   # 사설·루프백·공유 대역
    "224.0.0.1", "203.0.113.5", "121.134.5.0", "0.0.0.0",                  # 멀티캐스트·문서용·망 주소
    "OID 1.3.6.1.4.1.311", "1.2.3.4.5", "256.1.1.1", "v1.2.3.4", "Chrome/131.0.0.1",
])
def test_k1_wrong_checksum_region_layout_or_non_public_address_is_not_found(text):
    assert find_all(text) == []


# ---------- K2 외국인 번호·주민 꼴 법인번호 ----------

@pytest.mark.parametrize("gender, kind", [(g, "rrn") for g in "1234"] + [(g, "frn") for g in "5678"])
def test_k2_gender_digit_splits_rrn_and_frn(gender, kind):
    value = f"900101-{gender}234567"
    assert found(f"등록번호 {value}") == [(kind, value)]


@pytest.mark.parametrize("text, kind", [
    (f"법인등록번호 {CRN_RRN_SHAPE}", "crn"),          # 주민 꼴 + 법인 검증식 + '법인' 문맥 + 주민 검증식 실패
    (f'{{"corp_reg_no": "{CRN_RRN_SHAPE}"}}', "crn"),
    (f"(주)한빛 {CRN_RRN_SHAPE}", "rrn"),             # '법인' 문맥 없음 → 주민번호로 가린다(틀려도 가림 쪽)
    ("법인 대표 주민번호 900101-1234568", "rrn"),       # 주민 검증식 통과는 '법인' 문맥이 있어도 주민번호
    ("법인등록번호 1101111234569", "rrn"),              # 구분자 없는 꼴은 법인번호로 보지 않는다
])
def test_k2_rrn_shaped_corporate_number_needs_corp_context(text, kind):
    (f,) = find_all(text)
    assert f.kind == kind and f.mask


# ---------- K3 가릴지 ----------

@pytest.mark.parametrize("text, mask", [
    (f"{PASSPORT_OLD} 체크인", False), (f"여권 {PASSPORT_OLD}", True), (f"PASSPORT {PASSPORT_OLD}", True),
    (f"{PASSPORT_NEW} 체크인", True),
    (f"번호 {ACCOUNT} 확인", False), (f"신한 {ACCOUNT}", True), (f"account: {ACCOUNT}", True), (f"{ACCOUNT}로 송금", True),
    (f"접속 {IP}", True), ("펌웨어 2.4.1.3 업데이트", False), ("버전 2.4.1.3", False), ("build 2.4.1.3", False),
    ("패키지 2.4.1.3 설치", True),                      # 버전 문맥어 없는 4묶음 버전 — 한계(README)
    (f"번호 {DRIVER}", True), (f"번호 {BRN}", True), (f"번호 {CRN}", True),
    (f"신청인 {FRN_WEAK.replace('-', '')}", False), (f"외국인 {FRN_WEAK.replace('-', '')}", True), (f"신청인 {FRN_WEAK}", True),
])
def test_k3_context_decides_only_whether_to_mask(text, mask):
    (f,) = find_all(text)
    assert f.mask is mask


# ---------- K4 대체값 ----------

@pytest.mark.parametrize("kind, value", [(k, v) for k, vs in SAMPLES.items() for v in vs])
def test_k4_surrogate_keeps_the_shape_and_redetects_as_its_own_kind(kind, value):
    ctx = "법인 " if kind == "crn" else ""                    # 주민 꼴 법인번호의 대체값도 주민 꼴이다 — '법인' 문맥 없이는 rrn(K2)
    for _ in range(30):
        s = surrogate.make(kind, value)
        d, dv = digits(s), digits(value)
        # 주민 꼴 대체값이 주민 검증식까지 우연히 맞추면(약 10%) K2대로 rrn이다 — 복원 키는 같은 숫자열이라 되찾는 데는 상관없다
        expect = "rrn" if kind == "crn" and value == CRN_RRN_SHAPE and rrn_checksum_ok(d) else kind
        assert s != value
        assert [(f.kind, f.start, f.end) for f in find_all(ctx + s)] == [(expect, len(ctx), len(ctx + s))], (value, s)
        if kind != "ipv4":                                   # 구분자·글자 자리 유지(IP는 묶음 길이가 바뀔 수 있다)
            assert [c.isdigit() for c in s] == [c.isdigit() for c in value]
        if kind == "frn":
            assert d[6] in "5678" and rrn_date_ok(d[:2], d[2:4], d[4:6], d[6])
        if kind == "brn":
            assert d[:5] == dv[:5] and brn_check(d) == int(d[9])
        if kind == "crn":
            assert d[:7] == dv[:7] and crn_check(d) == int(d[12])
        if kind == "driver":
            assert d[:2] == dv[:2] and d[:2] in DRIVER_REGIONS
        if kind == "account":
            assert d[:3] == dv[:3] and tuple(map(len, s.split("-"))) in ACCOUNT_LAYOUTS
        if kind == "passport":
            assert s[0] == value[0] and [c.isupper() for c in s] == [c.isupper() for c in value]
        if kind == "ipv4":
            ip = ipaddress.IPv4Address(s)
            assert s.split(".")[0] == value.split(".")[0] and ip.is_global and not s.endswith(".0")
        if kind == "phone":
            assert d[:3] == "070"


def test_k4_frn_surrogate_does_not_keep_the_checksum():
    """대체값은 2020-10 이후 번호처럼 검증식을 맞추지 않는다(주민번호와 같은 규칙) — 다시 잡히는 것은 날짜·성별 덕이다."""
    rng = random.Random(7)
    assert sum(frn_checksum_ok(digits(surrogate.make("frn", FRN, rng))) for _ in range(200)) < 60


@pytest.mark.parametrize("kind, value", [(k, vs[0]) for k, vs in SAMPLES.items()])
def test_k4_same_key_same_value_same_surrogate(kind, value):
    key = b"k4" * 16
    assert TokenVault(key=key).token_for("a", kind, value) == TokenVault(key=key).token_for("b", kind, value)


# ---------- K5 기본 감사만 종류 ----------

MIXED = f"계좌 {ACCOUNT}, 사업자 {BRN}, 법인 {CRN}, 접속 {IP}, 연락처 010-2345-6789, 여권 {PASSPORT_NEW}, 면허 {DRIVER}, 외국인 {FRN}"


@pytest.mark.anyio
async def test_k5_business_numbers_accounts_and_ips_are_audited_not_masked_by_default():
    v = await PIIDetector("mask").inspect(chat_insp(MIXED))
    sent = json.loads(v.body)["messages"][0]["content"]
    assert all(x in sent for x in (ACCOUNT, BRN, CRN, IP))
    assert not any(x in sent for x in ("010-2345-6789", PASSPORT_NEW, DRIVER, FRN))
    assert v.meta["pii"] == {"phone": 1, "passport": 1, "driver": 1, "frn": 1}
    assert v.meta["unmasked"] == {"account": 1, "brn": 1, "crn": 1, "ipv4": 1}


@pytest.mark.anyio
async def test_k5_empty_detect_kinds_masks_everything():
    v = await PIIDetector("mask", detect_kinds=()).inspect(chat_insp(MIXED))
    sent = json.loads(v.body)["messages"][0]["content"]
    assert v.meta["masked"] == 8 and "unmasked" not in v.meta
    assert not any(x in sent for x in (ACCOUNT, BRN, CRN, IP))


def upstream_text(stack) -> str:
    return json.loads(httpx.get(stack.target + "/__stub/received").json()["bodies"][-1])["messages"][0]["content"]


def test_k5_gateway_setting_turns_masking_on_for_detect_only_kinds(make_stack):
    body = {"model": "stub-model", "messages": [{"role": "user", "content": MIXED}]}
    default = make_stack(GATEWAY_DETECTORS=None)
    assert httpx.post(default.gateway + CHAT, json=body).status_code == 200
    assert ACCOUNT in upstream_text(default) and IP in upstream_text(default)
    on = make_stack(GATEWAY_DETECTORS=None, GATEWAY_PII_DETECT_KINDS="")
    r = httpx.post(on.gateway + CHAT, json=body)
    assert r.status_code == 200 and ACCOUNT not in upstream_text(on) and IP not in upstream_text(on)
    assert ACCOUNT in r.text and IP in r.text                                    # 응답에서는 복원된다
    narrow = make_stack(GATEWAY_DETECTORS=None, GATEWAY_PII_KINDS="passport", GATEWAY_PII_DETECT_KINDS="")
    assert httpx.post(narrow.gateway + CHAT, json=body).status_code == 200
    sent = upstream_text(narrow)
    assert PASSPORT_NEW not in sent and ACCOUNT in sent and "010-2345-6789" in sent


@pytest.mark.parametrize("var", ["GATEWAY_PII_KINDS", "GATEWAY_PII_DETECT_KINDS"])
def test_k5_unknown_kind_name_does_not_boot(make_stack, var):
    with pytest.raises(RuntimeError, match="기동 실패"):
        make_stack(GATEWAY_DETECTORS=None, **{var: "rrn,iban"})


# ---------- K6 복원 ----------

def new_kind_values() -> list[tuple[str, str]]:
    return [("frn", FRN), ("brn", BRN), ("crn", CRN), ("crn", CRN_RRN_SHAPE), ("driver", DRIVER), ("account", ACCOUNT),
            ("passport", PASSPORT_OLD), ("passport", PASSPORT_NEW), ("ipv4", IP), ("phone", VOIP)]


@pytest.mark.anyio
async def test_k6_surrogates_come_back_even_without_the_context_words():
    det = PIIDetector("mask", detect_kinds=(), vault=TokenVault(key=b"k6" * 16))
    text = (f"외국인 {FRN} 사업자 {BRN} 법인 {CRN} 법인등록번호 {CRN_RRN_SHAPE} 면허 {DRIVER} 계좌 {ACCOUNT} "
            f"여권 {PASSPORT_OLD} {PASSPORT_NEW} 접속 {IP} 전화 {VOIP}")
    v = await det.inspect(chat_insp(text, session="k6"))
    sent = json.loads(v.body)["messages"][0]["content"]
    assert v.action is Action.TRANSFORM and v.meta["masked"] == 10
    surrogates = [sent[f.start:f.end] for f in find_all(sent)]
    assert len(surrogates) == 10 and not set(surrogates) & {x for _, x in new_kind_values()}
    answer = " / ".join(surrogates)                       # 모델이 문맥어 없이 값만 늘어놓아도
    restored, meta = await det.on_response("k6", reply(answer))
    assert json.loads(restored)["choices"][0]["message"]["content"] == " / ".join(x for _, x in new_kind_values())
    assert meta["restored"] == 10 and meta["residual_tokens"] == 0


def test_k6_stream_restores_new_kinds_across_every_chunk_boundary():
    vault = TokenVault(key=b"k6s" * 11)
    sur = {value: vault.token_for("s", kind, value) for kind, value in new_kind_values()}
    text = "값: " + ", ".join(sur.values()) + " 끝"
    expected = "값: " + ", ".join(sur) + " 끝"
    for size in range(1, 9):
        restorer = StreamRestorer(ChatShape(), lambda t, escape=None: vault.restore("s", t, escape), lambda t: vault.hold("s", t))
        raw = sse([text[i:i + size] for i in range(0, len(text), size)])
        out = restorer.feed(raw) + restorer.finish()
        assert content_of(out) == expected, size


def test_k6_hold_sees_dotted_and_lettered_prefixes():
    vault = TokenVault(key=b"k6h" * 11)
    ip, passport = vault.token_for("s", "ipv4", IP), vault.token_for("s", "passport", PASSPORT_NEW)
    for i in range(1, len(ip)):
        assert vault.hold("s", "주소 " + ip[:i]) == i, ip[:i]
    for i in range(1, len(passport)):
        assert vault.hold("s", "번호 " + passport[:i]) == i, passport[:i]


# ---------- K8 코퍼스 ----------

def test_k8_d115_lines_are_byte_identical():
    """D-117은 다른 시드로 뒤에 붙였다 — 앞의 1,500줄(D-115·D-116의 자)은 바이트까지 그대로다."""
    path = Path(__file__).resolve().parents[1] / "eval" / "pii" / "corpus.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(lines) == 2400
    assert hashlib.sha256("".join(lines[:1500]).encode()).hexdigest() == \
        "55d17f9b76730406c6de2603456cb81184470f52759d68ade3a3827e323d733c"


# ---------- K9 1MiB ----------

def test_k9_one_mib_with_new_kinds():
    unit = (f"외국인 {FRN}, 사업자 {BRN}, 법인 {CRN}, 면허 {DRIVER}, 계좌 {ACCOUNT}, 여권 {PASSPORT_NEW}, 접속 {IP}, "
            f"전화 {VOIP}, 서버 192.168.0.10, 버전 2.4.1.3, 주문 2026103012345 — ㈜한빛 ０１０－２３４５－６７８９. ")
    text = unit * (1024 * 1024 // len(unit.encode()) + 1)
    t0 = time.perf_counter()
    got = find_all(text)
    elapsed = time.perf_counter() - t0
    n = text.count(unit)
    kinds = {k: sum(f.kind == k for f in got) for k in ("frn", "brn", "crn", "driver", "account", "passport", "ipv4", "phone")}
    assert kinds == {"frn": n, "brn": n, "crn": n, "driver": n, "account": n, "passport": n, "ipv4": 2 * n, "phone": 2 * n}
    assert elapsed < 5.0
    print(f"1MiB {len(text.encode()) / 1e6:.2f}MB {elapsed:.2f}s")
