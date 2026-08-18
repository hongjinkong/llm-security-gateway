"""5단계 3차 LLM Judge — 순수 함수부. **모델 없이 전부 돈다.**

모델이 있어야만 도는 테스트는 실제로 안 돌게 되고, 안 도는 테스트는 없는 것과 같다.
그래서 판단 로직(게이팅·배선 검증·파싱)을 호출 로직에서 떼어냈다(D-047).
설계는 `docs/JUDGE_DESIGN.md` (D-053).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.detectors.judge import (
    GATE_ENV,
    GATE_G,
    JUDGE_NAME,
    OBSERVE_NAME,
    Judgement,
    JudgeParseError,
    JudgeTarget,
    JudgeVerdict,
    JudgeWiringError,
    parse_judgement,
    should_judge,
    similarity_from_prior,
    threshold_from_env,
    validate_chain_order,
)

CALIB = (Path(__file__).resolve().parents[1] / "results" / "calibration"
         / "calibration_20260818T024113Z.json")


# ---------- G가 데이터에서 왔음을 고정한다 (D-053) ----------

def test_gate_g_equals_min_loo_of_the_committed_calibration():
    """**이 테스트가 G의 정당성 전부다.**

    D-053은 G를 `min(LOO)`로 정했다. 사람이 구간 안에서 골라잡은 값이 아니라는 것이
    그 결정의 근거였다. 상수를 조용히 올리면 정상 도달률이 내려가 Judge 오탐 기회가
    줄고 FPR이 좋아 보인다 — 인센티브가 뒤집혀 있다(D-053 (8)). 그래서 상수를
    **출처 데이터에 묶어둔다.**
    """
    assert CALIB.exists(), f"캘리브레이션 산출물이 없다: {CALIB}"
    d = json.loads(CALIB.read_text(encoding="utf-8"))
    loo_min = min(r["loo_max"] for r in d["per_corpus"])
    assert GATE_G == pytest.approx(loo_min, abs=5e-7), (
        f"GATE_G={GATE_G}가 산출물의 min(LOO)={loo_min}과 다르다")


def test_every_corpus_item_reaches_stage3_at_g():
    """게이트의 존재 이유: 알려진 공격 유형이 전부 3차에 도달해야 한다."""
    d = json.loads(CALIB.read_text(encoding="utf-8"))
    missed = [r["id"] for r in d["per_corpus"] if not should_judge(r["loo_max"], GATE_G)]
    assert missed == [], f"3차에 도달하지 못하는 코퍼스 항목: {missed}"


def test_only_b111_of_the_benign_set_reaches_stage3_at_g():
    """3차가 FPR을 건드릴 수 있는 최대치가 1문항으로 데이터에 묶여 있다(D-053).

    이 숫자가 늘면 3차의 오탐 위험이 커진 것이므로 조용히 지나가면 안 된다.
    """
    d = json.loads(CALIB.read_text(encoding="utf-8"))
    reach = sorted(r["id"] for r in d["per_benign"] if should_judge(r["score"], GATE_G))
    assert reach == ["B-111"], f"기대 ['B-111'], 실제 {reach}"


# ---------- 게이팅 ----------

def test_similarity_is_read_from_the_observe_step():
    prior = {OBSERVE_NAME: {"similarity": 0.7123, "nearest_id": "K-R1-08"}}
    assert similarity_from_prior(prior) == pytest.approx(0.7123)


def test_missing_observe_is_a_wiring_error_not_a_silent_pass():
    """배선 사고를 정상 동작으로 위장하지 않는다. 조용히 통과시키면 3차가 꺼진 채
    '3차 ON'으로 측정된다 — chain.py가 '가장 나쁜 실패'라고 부른 것."""
    with pytest.raises(JudgeWiringError):
        similarity_from_prior({"injection_rule": {}})


def test_observe_ran_but_skipped_is_none_not_an_error():
    """빈 입력은 observe가 건너뛴다. 배선은 멀쩡하므로 오류가 아니다."""
    prior = {OBSERVE_NAME: {"similarity_skipped": "empty_input", "mode": "observe"}}
    assert similarity_from_prior(prior) is None


@pytest.mark.parametrize("score,want", [
    (GATE_G, True),            # 경계값 자체는 회부한다 (>=)
    (GATE_G + 1e-9, True),
    (GATE_G - 1e-6, False),
    (0.0, False),
    (None, False),             # 빈 입력 — 판단할 내용이 없다
])
def test_should_judge_boundary(score, want):
    assert should_judge(score, GATE_G) is want


# ---------- 임계값 출처 ----------

def test_threshold_defaults_to_the_frozen_value():
    g, src = threshold_from_env({})
    assert g == GATE_G and src == "frozen"


def test_env_override_is_recorded_as_such():
    """덮어썼다는 사실을 숨기지 않는다. G 상향은 FPR을 좋아 보이게 만든다(D-053)."""
    g, src = threshold_from_env({GATE_ENV: "0.70"})
    assert g == pytest.approx(0.70) and src == "env"


def test_empty_env_value_is_treated_as_unset():
    """`GATEWAY_JUDGE_G=`로 '껐다'가 '0.0으로 설정'으로 오독되면 전량 호출이 된다."""
    g, src = threshold_from_env({GATE_ENV: "  "})
    assert g == GATE_G and src == "frozen"


@pytest.mark.parametrize("bad", ["abc", "1.5", "-2"])
def test_bad_env_value_raises(bad):
    with pytest.raises(ValueError):
        threshold_from_env({GATE_ENV: bad})


# ---------- 배선 검증 ----------

def test_chain_without_judge_is_always_fine():
    validate_chain_order(["injection_rule", "pii_mask"])


def test_correct_order_passes():
    validate_chain_order(["injection_rule", OBSERVE_NAME, JUDGE_NAME, "pii_mask"])


def test_judge_without_observe_fails_to_start():
    with pytest.raises(JudgeWiringError):
        validate_chain_order(["injection_rule", JUDGE_NAME, "pii_mask"])


def test_observe_after_judge_fails_to_start():
    """앞 단계의 판정만 prior에 담긴다. 순서가 뒤집히면 게이팅 점수가 빈다."""
    with pytest.raises(JudgeWiringError):
        validate_chain_order([JUDGE_NAME, OBSERVE_NAME])


def test_blocking_similarity_does_not_satisfy_the_requirement():
    """차단형 `injection_similarity`는 T가 동결되지 못해 쓰지 않기로 했다(D-052).

    여기서 받아주면 '쓰지 않기로 한 검사기'가 3차를 통해 되살아난다.
    """
    with pytest.raises(JudgeWiringError):
        validate_chain_order(["injection_similarity", JUDGE_NAME])


# ---------- 파싱 ----------

def test_clean_json_parses():
    j = parse_judgement('{"verdict":"attack","target":"system_instruction","reason":"근거"}')
    assert j.verdict is JudgeVerdict.ATTACK
    assert j.target is JudgeTarget.SYSTEM_INSTRUCTION
    assert j.is_attack is True


@pytest.mark.parametrize("raw", [
    '```json\n{"verdict":"benign","target":"user_utterance"}\n```',
    '판정 결과입니다.\n{"verdict":"benign","target":"user_utterance"}\n이상입니다.',
    '  {"verdict": "BENIGN", "target": "User_Utterance"}  ',
])
def test_parser_is_lenient_about_wrapping_and_case(raw):
    """모델은 코드펜스와 잡담으로 감싸는 일이 흔하다. 거기까지는 실패로 치지 않는다."""
    j = parse_judgement(raw)
    assert j.verdict is JudgeVerdict.BENIGN and j.target is JudgeTarget.USER_UTTERANCE


@pytest.mark.parametrize("raw", [
    '{"verdict":"maybe","target":"none"}',            # 스키마 밖 verdict
    '{"verdict":"attack","target":"unknown_thing"}',  # 스키마 밖 target
    '{"verdict":"attack"}',                           # target 누락
    '{"target":"none"}',                              # verdict 누락
    '"그냥 문자열"',                                    # 객체가 아니다
    '',                                               # 빈 출력
    '판정을 내릴 수 없습니다',                            # JSON 없음
])
def test_parser_is_strict_about_field_values(raw):
    """관대함의 한계선. 모르는 값을 어느 쪽으로든 해석하면 판정이 우리 상상이 된다."""
    with pytest.raises(JudgeParseError):
        parse_judgement(raw)


def test_reason_is_truncated():
    j = parse_judgement(json.dumps(
        {"verdict": "benign", "target": "none", "reason": "가" * 1000}))
    assert len(j.reason) == 300


# ---------- 원문 유출 방지 ----------

def test_log_meta_never_carries_the_reason():
    """**JUDGE_DESIGN 4.1.** 모델이 근거를 쓰며 사용자 원문을 인용할 수 있다.
    로그에 들어가면 D-029(원문 미기록)와 garak 런의 D-039(홀드아웃)가 함께 깨진다.
    """
    secret = "제 주민등록번호는 900101-1234563입니다"
    j = Judgement(JudgeVerdict.BENIGN, JudgeTarget.NONE, reason=secret)
    meta = j.as_log_meta()
    assert meta == {"judge_verdict": "benign", "judge_target": "none"}
    assert secret not in json.dumps(meta, ensure_ascii=False)
    assert "reason" not in meta
