"""4-D 검증: PII 탐지기. 데이터는 전부 합성이다(SCOPE 6절)."""
from __future__ import annotations

import pytest

from gateway.detectors.pii import (Finding, PIIDetector, find_all, luhn_ok,
                                   rrn_checksum_ok, rrn_date_ok)
from gateway.detectors.base import Action, Inspection


def kinds(text: str) -> list[str]:
    return [f.kind for f in find_all(text)]


def spans(text: str) -> list[str]:
    return [text[f.start:f.end] for f in find_all(text)]


# ---------- 실제 정상 질문셋(all100.jsonl)에서 가져온 문장 ----------

@pytest.mark.parametrize("text,expect", [
    ("주민등록번호 900101-1234563입니다. 만 35세 이상 건강검진 주기가 어떻게 되나요?", ["rrn"]),
    ("제 주민등록번호는 880315-2345671입니다. 병가는 연간 며칠까지 쓸 수 있나요?", ["rrn"]),
    ("950720-1456782 본인 확인용입니다. 식대는 월 얼마까지 비과세인가요?", ["rrn"]),
    ("법인카드 4111-1111-1111-1111로 결제했습니다.", ["card"]),
    ("개인카드 5500-0000-0000-0004로 건강검진비를 결제했는데", ["card"]),
    ("제 번호는 010-2345-6789입니다.", ["phone"]),
    ("제 사내 메일 j.hong@hanbit-tech.example로 답변 주세요.", ["email"]),
    ("이수진이고 연락처는 010-5566-7788입니다.", ["phone"]),
])
def test_detects_benign_set_pii(text, expect):
    assert kinds(text) == expect


# ---------- 오탐 (여기가 FPR을 지킨다) ----------

@pytest.mark.parametrize("text", [
    "표준 근무시간은 몇 시부터 몇 시까지인가요?",
    "2026-08-07 회의는 09:00부터입니다.",
    "인사팀 내선번호는 3300번입니다.",
    "사번 20210233으로 조회해 주세요.",
    "계좌 110-234-567890으로 급여를 받고 있습니다.",      # SCOPE 밖 + 전화번호 오인 금지
    "계좌 302-1122-3344-55로 퇴직금은 며칠 이내에 지급되나요?",  # 앞부분만 잘라 전화번호로 보면 안 됨
    "동호회 지원금은 인당 분기에 5만원입니다.",
])
def test_no_false_positive(text):
    assert find_all(text) == []


def test_account_number_is_out_of_scope_not_a_bug():
    """계좌번호는 SCOPE 4.2에 없다. 미탐지가 정상이며 README 한계로 명시한다."""
    assert kinds("계좌 302-1122-3344-55로 보내주세요") == []


# ---------- 주민번호 등급 ----------

def test_rrn_weak_when_checksum_fails():
    """2020-10 개편 이후 발급분과 우리 합성 데이터가 여기 해당한다. 놓치면 유출이다."""
    (f,) = find_all("주민등록번호 900101-1234563입니다.")
    assert f.kind == "rrn" and f.confidence == "weak"


def test_rrn_strong_when_checksum_passes():
    # 900101-123456X 에서 검증식을 만족하는 X는 8
    (f,) = find_all("주민등록번호 900101-1234568입니다.")
    assert f.confidence == "strong"
    assert rrn_checksum_ok("9001011234568")


@pytest.mark.parametrize("text", [
    "991301-1234567",   # 13월
    "900132-1234567",   # 32일
    "900101-9234567",   # 성별코드 9는 이 패턴에서 제외
])
def test_invalid_rrn_is_rejected(text):
    assert "rrn" not in kinds(text)


def test_rrn_date_and_century():
    assert rrn_date_ok("00", "02", "29", "3")     # 2000년은 윤년
    assert not rrn_date_ok("01", "02", "29", "3")  # 2001년은 아님


# ---------- 카드 ----------

def test_card_requires_luhn():
    assert luhn_ok("4111111111111111")
    assert not luhn_ok("1234567890123456")
    assert kinds("카드 1234-5678-9012-3456으로 결제") == []


def test_rrn_wins_over_card_on_overlap():
    """13자리 주민번호가 카드 패턴에도 걸린다. 우선순위로 한 번만 잡혀야 한다."""
    out = find_all("900101-1234563")
    assert len(out) == 1 and out[0].kind == "rrn"


# ---------- 여러 개 / 검사기 계약 ----------

def test_multiple_pii_in_one_message():
    text = "이수진 010-5566-7788, s.kim@hanbit-tech.example, 카드 4111-1111-1111-1111"
    assert kinds(text) == ["phone", "email", "card"]


@pytest.mark.anyio
async def test_detector_only_detects_never_acts():
    """4-D는 탐지 전용. 판정은 항상 ALLOW이고 본문을 바꾸지 않는다."""
    body = "주민등록번호 900101-1234563입니다.".encode()
    v = await PIIDetector().inspect(
        Inspection(request_id="r", method="POST", path="/chat", headers={}, body=body))
    assert v.action is Action.ALLOW
    assert v.body is None
    assert v.meta["pii"] == {"rrn": 1}


@pytest.mark.anyio
async def test_findings_never_contain_the_raw_value():
    """D-029: 로그로 나가는 정보에 원문이 섞이면 안 된다."""
    body = "카드 4111-1111-1111-1111".encode()
    v = await PIIDetector().inspect(
        Inspection(request_id="r", method="POST", path="/chat", headers={}, body=body))
    assert "4111" not in str(v.meta)


@pytest.fixture
def anyio_backend():
    return "asyncio"
