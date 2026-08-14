"""캘리브레이션 계산 테스트 — D-049-1 절차가 코드에서 그대로 지켜지는지.

`calibrate()`는 **순수 함수**다. 벡터를 직접 넣어 상황을 만든다 — 임베더도 Ollama도
파일도 쓰지 않는다. `FakeEmbedder`를 만든 것과 같은 이유다(D-047): 결과를 읽기만 해서는
"나온 값이 나왔다"가 되고, 그런 테스트는 계산이 틀려도 통과한다.

*** 여기서 제일 중요한 세 가지 ***
1. `test_clean_corpus_drops_nothing` — 게이트가 **"0 탈락"을 말할 수 있어야 한다.**
   초안(p95 분위수)이 폐기된 이유가 이것이다. 상대 규칙이라 코퍼스가 정상 질문과
   완전히 무관해도 항상 상위 몇 개를 잘라냈다(D-049-1).
2. `test_no_gap_means_no_threshold` — 갭이 없으면 **T를 정하지 않는다.**
   억지로 숫자를 뽑으면 D-044가 금지한 "한 축만 보고 선 긋기"가 된다.
3. `test_gate_runs_only_once` — 게이트를 두 번 돌리면 통과할 때까지 도는 최적화가 되고,
   그 순간 게이트는 아무것도 측정하지 않는다(D-049 결정 2).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from calibrate_similarity import calibrate, pct  # noqa: E402


def mat(*degs: float) -> np.ndarray:
    """각도로 단위벡터를 만든다. 두 각도의 코사인 유사도 = cos(각도차)라 상황을 지정하기 쉽다."""
    return np.asarray(
        [[math.cos(math.radians(d)), math.sin(math.radians(d))] for d in degs],
        dtype=np.float32)


def spread(lo: float, hi: float, n: int, seed: int = 0) -> list[float]:
    return list(np.random.default_rng(seed).uniform(lo, hi, n))


# --- 백분위: 다른 스크립트와 같은 방식이어야 한다 -------------------------------

def test_percentile_is_nearest_rank_not_interpolated():
    """선형 보간을 쓰면 같은 데이터에서 다른 숫자가 나온다(D-035).
    `fpr_report.py`·`embed_latency.py`와 방식이 같아야 숫자를 나란히 놓을 수 있다."""
    vals = [float(i) for i in range(100)]           # 0..99
    assert pct(vals, 0.95) == 95.0                  # int(100*0.95) = 95
    assert pct(vals, 0.50) == 50.0
    assert pct([], 0.95) == 0.0
    assert pct([7.0], 0.95) == 7.0                  # 인덱스가 넘치지 않는다


# --- 게이트: benign_max(j) > loo_max(j) (D-049-1) ------------------------------

def test_clean_corpus_drops_nothing():
    """**이 테스트가 D-049-1 개정의 이유다.**

    코퍼스는 0~20도에 있고 정상 질문은 110~170도다 — 90도 이상 떨어져 있어
    benign_max가 음수까지 내려간다. 여기서 무언가 탈락한다면 그 게이트는
    '너무 가까우면 뺀다'를 재는 게 아니라 그냥 상위 몇 개를 자르는 것이다.

    폐기한 초안(p95 분위수)은 이 상황에서 **5항목을 잘라냈다.**
    """
    C = mat(*spread(0, 20, 52))
    B = mat(*spread(110, 170, 100, seed=1))
    cal = calibrate(C, B)
    assert float(cal.benign_max_all.max()) < 0.5, "이 시나리오는 코퍼스가 정상과 멀어야 성립한다"
    assert cal.dropped_idx == [], "정상과 무관한 코퍼스는 한 항목도 빠지지 않는다"
    assert len(cal.kept_idx) == 52


def test_gate_drops_exactly_the_items_planted_next_to_benign_questions():
    C_deg = spread(0, 20, 49)
    B_deg = spread(110, 170, 100, seed=1)
    C = mat(*(C_deg + [B_deg[0] + 0.1, B_deg[1] + 0.1, B_deg[2] + 0.1]))
    cal = calibrate(C, mat(*B_deg))
    assert cal.dropped_idx == [49, 50, 51], "정상 질문 위에 얹은 3개만 빠져야 한다"


def test_a_spread_out_corpus_is_not_punished_for_being_diverse():
    """기법 축을 나눠 표현 다양성을 확보한 것(D-045·D-046)이 게이트에서 불리하면 안 된다.
    코퍼스가 0~90도로 흩어져 있어도, 여전히 정상 질문보다는 서로가 가깝다 —
    그게 2차 방어의 전제 자체다."""
    C = mat(*spread(0, 90, 52, seed=2))
    B = mat(*spread(110, 170, 100, seed=1))
    assert calibrate(C, B).dropped_idx == []


def test_gate_uses_strict_greater_not_greater_equal():
    """D-049-1은 'loo_max보다 **높으면**'(strictly greater) 뺀다. 정확히 같으면 남는다 —
    규칙 문구와 코드가 어긋나면 나중에 둘 중 무엇이 진짜인지 알 수 없다."""
    # 항목 0의 정상 최근접과 코퍼스 최근접이 정확히 같은 각도차(10도)에 있다.
    C = mat(0, 10)
    B = mat(-10, 200)
    cal = calibrate(C, B)
    assert float(cal.benign_max_all[0]) == pytest.approx(float(cal.loo_all[0]), abs=1e-6)
    assert 0 not in cal.dropped_idx, "같은 값은 탈락하지 않는다"


def test_gate_runs_only_once():
    """**D-049 결정 (2).** 뺀 뒤 재계산해서 또 빼지 않는다.

    확인 방법: 1회차에 빠진 항목을 제거하고 나면 2회차에 더 빠질 항목이 생기는 상황을
    만들고, `calibrate()`가 그 항목을 **남겨두는지** 본다. 반복하면 통과할 때까지 도는
    최적화가 되고, 그 순간 게이트는 아무것도 측정하지 않는다.
    """
    # 0도·1도는 서로 붙어 있다. 60도는 최근접이 100도(40도차)라 loo가 0.766인데
    # 정상질문 30도(30도차, 0.866)가 더 가까워 1회차에 빠진다.
    # 60도가 빠지고 나면 100도의 최근접이 1도(99도차)로 멀어져 2회차라면 빠진다.
    C = mat(0, 1, 60, 100)
    B = mat(30, 200, 210)
    cal = calibrate(C, B)
    assert cal.dropped_idx == [2], "60도만 1회차에 빠진다"
    assert 3 in cal.kept_idx, "100도는 1회차 기준으로는 남는다"

    cal2 = calibrate(C[cal.kept_idx], B)
    assert cal2.dropped_idx == [2], "2회차라면 100도가 빠지는 시나리오다"
    # 핵심: calibrate()가 그 2회차를 스스로 수행하지 않았다.
    assert cal.kept_idx == [0, 1, 3]


def test_too_few_survivors_raises_instead_of_guessing():
    """전량 탈락에 가까우면 '규칙을 고치자'가 아니라 코퍼스를 다시 본다(D-044)."""
    B_deg = spread(0, 5, 100)
    C = mat(*[B_deg[0] + 0.01, B_deg[1] + 0.01])   # 코퍼스가 통째로 정상 질문 위에 있다
    with pytest.raises(ValueError, match="코퍼스를 다시"):
        calibrate(C, mat(*B_deg))


def test_gate_compares_against_full_corpus_loo_not_survivors():
    """게이트 판정은 **전체 코퍼스 기준** LOO와 비교한다. 잔존분 기준으로 하면
    빼는 순서에 따라 결과가 달라져 결정론이 깨진다."""
    C = mat(*spread(0, 20, 52))
    B = mat(*spread(110, 170, 100, seed=1))
    cal = calibrate(C, B)
    assert cal.loo_all.shape == (52,), "판정용 LOO는 전체 코퍼스 길이여야 한다"


# --- 두 분포와 갭 ---------------------------------------------------------------

def test_loo_excludes_self():
    """자기 자신을 포함하면 LOO 최근접이 항상 1.0이 되어 갭이 가짜로 넓어진다 —
    D-044의 '자기 복제' 위험이 그대로 실현된다."""
    C = mat(0, 40, 80)
    B = mat(180, 175)
    cal = calibrate(C, B, budget=1)
    assert float(cal.loo_max.max()) < 0.9999, "자기 자신이 최근접이 되면 안 된다"
    assert float(cal.loo_max[0]) == pytest.approx(math.cos(math.radians(40)), abs=1e-4)


def test_gap_positive_gives_midpoint_threshold():
    C = mat(0, 5, 10)
    B = mat(90, 95, 100)
    cal = calibrate(C, B, budget=1)
    assert cal.gap > 0
    assert cal.T == pytest.approx((cal.lo + cal.hi) / 2)
    assert cal.lo < cal.T < cal.hi, "T는 두 분포 사이에 있어야 한다"


def test_no_gap_means_no_threshold():
    """**D-044의 핵심.** 갭이 없으면 T를 뽑지 않는다 —
    '갭이 없으면 코퍼스를 다시 짜라는 신호'다."""
    # 코퍼스는 붙어 있는 두 쌍(0·2도, 100·102도)과 외톨이 하나(200도)로 짠다.
    # 외톨이는 정상질문에서도 멀어 게이트를 **통과**하지만 LOO가 -0.14로 낮다.
    # 그래서 LOO 분포의 아래가 정상 분포의 위보다 낮아져 갭이 닫힌다.
    C = mat(0, 2, 100, 102, 200)
    B = mat(50, 55)
    cal = calibrate(C, B, budget=1)
    assert cal.dropped_idx == [], "이 시나리오는 게이트를 통과해야 성립한다"
    assert cal.gap <= 0
    assert cal.T is None, "갭이 없으면 T를 정하지 않는다"


def test_budget_floor_is_the_fifth_highest_benign_score():
    """예산 4개 → 5번째로 높은 정상 점수보다 T가 커야 한다(판정은 score >= T).
    예산은 **제약이지 목적이 아니다** — T를 이 값으로 잡지 않는다(D-044)."""
    C = mat(0, 0.5, 1)
    B = mat(10, 11, 12, 13, 14, 90, 91)
    cal = calibrate(C, B, budget=4)
    assert cal.dropped_idx == []
    desc = sorted((float(v) for v in cal.benign_nearest), reverse=True)
    assert cal.budget_floor == pytest.approx(desc[4])


def test_budget_floor_is_zero_when_benign_set_is_smaller_than_budget():
    cal = calibrate(mat(0, 30), mat(90, 120), budget=4)
    assert cal.budget_floor == 0.0


# --- 방어적 입력 검사 -----------------------------------------------------------

def test_dimension_mismatch_raises():
    with pytest.raises(ValueError, match="차원"):
        calibrate(np.zeros((3, 2), dtype=np.float32), np.zeros((3, 4), dtype=np.float32))


def test_single_item_corpus_raises():
    """LOO를 계산할 수 없다. 조용히 0을 돌려주면 갭이 가짜로 계산된다."""
    with pytest.raises(ValueError, match="2항목 이상"):
        calibrate(mat(0), mat(90), budget=1)


def test_nearest_ids_point_at_the_surviving_corpus_not_the_original():
    """게이트로 항목을 뺐으므로 인덱스가 밀린다. 여기가 어긋나면 산출물의
    최근접 ID가 통째로 거짓말이 된다."""
    C_deg = spread(0, 20, 50)
    B_deg = spread(110, 170, 100, seed=1)
    C = mat(*(C_deg + [B_deg[0] + 0.1, B_deg[1] + 0.1]))
    cal = calibrate(C, mat(*B_deg))
    assert cal.dropped_idx == [50, 51]
    assert int(cal.benign_near_idx.max()) < len(cal.kept_idx)
    assert int(cal.loo_near_idx.max()) < len(cal.kept_idx)
    assert cal.benign_nearest.shape == (100,)
    assert cal.loo_max.shape == (len(cal.kept_idx),)
