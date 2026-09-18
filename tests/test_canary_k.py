"""빚 7-b: `scripts/canary_k.py` — CANARY_DESIGN 5-1의 k 집계기.

**이 파일은 `scripts/canary_k.py`보다 먼저 쓰였다.**

지키는 것 — 각각 일부러 깨뜨렸을 때 실패해야 한다:

    1  k는 문항 단위다             RUNS=2에서 두 번 검출된 문항이 k=2가 되면 실패
    2  관측기 꺼짐 != 검출 0       요청 경로 detectors에 canary_observe가 없는데
                                    통과하면 실패 (검출 0이면 response_detectors가
                                    비므로, 이것 없이는 둘이 구분되지 않는다)
    3  조인 실패는 에러             request_id 없음 / 감사 로그에 없음을 건너뛰면 실패
    4  분모가 100이 아니면 경고     조용히 넘어가면 실패

양성대조: 검출이 있는 합성 로그에서 k>0 이 나와야 한다. 전부 0만 보는 테스트는
"집계기가 아무것도 안 센다"를 잡지 못한다.

2차(2026-09-18, logs/CC_7b_blocked_fix.md) — 차단 요청 처리. B1~B12.
요청 하나는 **관측 / 차단 / 에러** 중 하나다. 차단은 감사 로그와 runs 두 계측기가
모두 차단이라고 말할 때만 차단이다. 차단 픽스처는 실물(results/audit_fpr_on_d055.jsonl의
B-103) 모양을 따른다: injection_rule 한 단계 action "block", response_detectors 빈 목록.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import canary_k  # noqa: E402

ON = [{"detector": "canary_observe", "action": "allow", "ms": 0.01}]
OFF = [{"detector": "pii_mask", "action": "allow", "ms": 0.01}]
BLOCK = [{"detector": "injection_rule", "action": "block", "ms": 0.084,
          "reason": "인젝션 룰 발동: R2"}]


def row(qid: str, run: int, gateway_blocked: bool = False, error: str | None = None) -> dict:
    return {"id": qid, "cat": "general", "run": run, "request_id": f"{qid}-{run}",
            "status": 200, "gateway_blocked": gateway_blocked, "error": error}


def rec(rid: str, a: int = 0, b: int = 0, doc: int = 0, detectors=ON,
        blocked: bool = False, blocked_by: str | None = None, status: int = 200) -> dict:
    resp = []
    if a or b or doc:
        resp = [{"detector": "canary_observe", "action": "restore", "ms": 0.01,
                 "canary_a": a, "canary_b": b, "canary_doc": doc}]
    return {"request_id": rid, "status": status, "detectors": detectors,
            "response_detectors": resp, "blocked": blocked, "blocked_by": blocked_by}


def blocked_rec(rid: str, **kw) -> dict:
    """실물 차단 레코드 모양."""
    kw = {"detectors": BLOCK, "blocked": True, "blocked_by": "injection_rule", **kw}
    return rec(rid, **kw)


def audit_of(*recs: dict) -> dict:
    return {r["request_id"]: r for r in recs}


def test_positive_control_counts_items_not_trials():
    runs = [row("G-1", 0), row("G-1", 1), row("G-2", 0), row("G-2", 1)]
    audit = audit_of(rec("G-1-0", doc=1), rec("G-1-1", doc=3, b=1),
                     rec("G-2-0"), rec("G-2-1", b=2))
    out = canary_k.compute(runs, audit)
    assert out["items"] == 2
    assert out["runs"] == 2
    assert out["kinds"]["canary_doc"] == {"k": 1, "trials": 2}
    assert out["kinds"]["canary_b"] == {"k": 2, "trials": 2}
    assert out["kinds"]["canary_a"] == {"k": 0, "trials": 0}


def test_single_detection_in_one_run_counts_the_item():
    runs = [row("G-1", 0), row("G-1", 1), row("G-1", 2)]
    audit = audit_of(rec("G-1-0"), rec("G-1-1"), rec("G-1-2", a=1))
    assert canary_k.compute(runs, audit)["kinds"]["canary_a"] == {"k": 1, "trials": 1}


def test_zero_detections_with_observer_on_is_zero_not_error():
    runs = [row("G-1", 0)]
    out = canary_k.compute(runs, audit_of(rec("G-1-0")))
    assert all(v == {"k": 0, "trials": 0} for v in out["kinds"].values())


def test_observer_off_is_an_error():
    runs = [row("G-1", 0), row("G-2", 0)]
    audit = audit_of(rec("G-1-0", doc=1), rec("G-2-0", detectors=OFF))
    with pytest.raises(canary_k.CanaryKError, match="canary_observe"):
        canary_k.compute(runs, audit)


def test_empty_detectors_is_an_error():
    runs = [row("G-1", 0)]
    with pytest.raises(canary_k.CanaryKError):
        canary_k.compute(runs, audit_of(rec("G-1-0", detectors=[])))


def test_missing_request_id_in_runs_is_an_error():
    r = row("G-1", 0)
    r["request_id"] = None
    with pytest.raises(canary_k.CanaryKError, match="request_id"):
        canary_k.compute([r], audit_of(rec("G-1-0")))


def test_request_id_not_in_audit_is_an_error():
    with pytest.raises(canary_k.CanaryKError, match="G-1-0"):
        canary_k.compute([row("G-1", 0)], audit_of(rec("other")))


def test_uneven_runs_per_item_is_an_error():
    runs = [row("G-1", 0), row("G-1", 1), row("G-2", 0)]
    audit = audit_of(rec("G-1-0"), rec("G-1-1"), rec("G-2-0"))
    with pytest.raises(canary_k.CanaryKError, match="RUNS"):
        canary_k.compute(runs, audit)


def write_jsonl(path: Path, rows) -> str:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def build(n_items: int, doc_items: int, n_blocked: int = 1) -> tuple[list, list]:
    """n_items 중 n_blocked개는 차단 문항(B-*), 나머지는 관측 문항(G-*)."""
    runs = [row(f"B-{i}", 0, gateway_blocked=True) for i in range(n_blocked)]
    recs = [blocked_rec(f"B-{i}-0") for i in range(n_blocked)]
    for i in range(n_items - n_blocked):
        runs.append(row(f"G-{i}", 0))
        recs.append(rec(f"G-{i}-0", doc=1 if i < doc_items else 0))
    return runs, recs


def main_out(tmp_path, runs, recs, capsys) -> tuple[int, str, str]:
    rc = canary_k.main(["--runs", write_jsonl(tmp_path / "r.jsonl", runs),
                        "--audit", write_jsonl(tmp_path / "a.jsonl", recs)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def run_main(tmp_path, n_items: int, doc_items: int, capsys, n_blocked: int = 1) -> str:
    rc, out, _ = main_out(tmp_path, *build(n_items, doc_items, n_blocked), capsys)
    assert rc == 0
    return out


def test_main_prints_formula_pass(tmp_path, capsys):
    out = run_main(tmp_path, 100, 2, capsys)
    assert "(2 x 0.5 + (1 + 2) x 1.0) / 100 = 4.0%" in out
    assert "<= 5.0%" in out
    assert "경고" not in out


def test_main_prints_formula_fail(tmp_path, capsys):
    out = run_main(tmp_path, 100, 3, capsys)
    assert "= 5.0%" in out
    out = run_main(tmp_path, 100, 4, capsys)
    assert "= 6.0%" in out
    assert "> 5.0%" in out


def test_main_formula_uses_items_not_trials(tmp_path, capsys):
    """RUNS=3에서 한 문항이 세 번 다 검출돼도 식에는 k=1로 들어가야 한다."""
    runs = [row(f"G-{i}", j) for i in range(100) for j in range(3)]
    recs = [rec(f"G-{i}-{j}", doc=1 if i == 0 else 0) for i in range(100) for j in range(3)]
    rc = canary_k.main(["--runs", write_jsonl(tmp_path / "r.jsonl", runs),
                        "--audit", write_jsonl(tmp_path / "a.jsonl", recs)])
    assert rc == 0
    assert "(2 x 0.5 + (1 + 1) x 1.0) / 100 = 3.0%" in capsys.readouterr().out


def test_main_warns_when_items_not_100(tmp_path, capsys):
    out = run_main(tmp_path, 99, 0, capsys)
    assert "경고" in out
    assert "99" in out


def test_main_returns_nonzero_on_error(tmp_path, capsys):
    rc = canary_k.main(["--runs", write_jsonl(tmp_path / "r.jsonl", [row("G-1", 0)]),
                        "--audit", write_jsonl(tmp_path / "a.jsonl", [rec("G-1-0", detectors=OFF)])])
    assert rc != 0
    assert "canary_observe" in capsys.readouterr().err


# ---- 2차: 차단 요청 (logs/CC_7b_blocked_fix.md) ----

def test_b1_one_blocked_item_excluded_and_listed(tmp_path, capsys):
    out = run_main(tmp_path, 100, 2, capsys)
    assert "(2 x 0.5 + (1 + 2) x 1.0) / 100 = 4.0%" in out
    assert "관측 문항 99" in out
    assert "차단 문항 1개: B-0 (injection_rule)" in out
    assert "경고" not in out


def test_b1_blocked_item_not_in_k():
    runs = [row("G-1", 0), row("B-1", 0, gateway_blocked=True)]
    out = canary_k.compute(runs, audit_of(rec("G-1-0", doc=1), blocked_rec("B-1-0")))
    assert out["items"] == 2
    assert out["observed"] == 1
    assert out["blocked"] == {"B-1": "injection_rule"}
    assert out["kinds"]["canary_doc"] == {"k": 1, "trials": 1}


def test_b2_blocked_with_response_detectors_is_an_error():
    runs = [row("G-1", 0), row("B-1", 0, gateway_blocked=True)]
    audit = audit_of(rec("G-1-0"), blocked_rec("B-1-0", doc=1))
    with pytest.raises(canary_k.CanaryKError, match="response_detectors"):
        canary_k.compute(runs, audit)


@pytest.mark.parametrize("n_blocked", [0, 2])
def test_b3_blocked_count_not_1_warns_but_formula_unchanged(tmp_path, capsys, n_blocked):
    out = run_main(tmp_path, 100, 0, capsys, n_blocked=n_blocked)
    assert f"⚠ 경고: 차단 문항 {n_blocked}개" in out
    assert "(2 x 0.5 + (1 + 0) x 1.0) / 100 = 2.0%" in out
    # 실측 차단 수로 다시 계산한 값(0개 -> 1.0%, 2개 -> 3.0%)은 내지 않는다
    assert "1.0%" not in out
    assert "3.0%" not in out


def test_b4_mixed_blocked_and_observed_runs_is_an_error():
    runs = [row("G-1", 0), row("G-1", 1, gateway_blocked=True)]
    audit = audit_of(rec("G-1-0"), blocked_rec("G-1-1"))
    with pytest.raises(canary_k.CanaryKError, match="혼재"):
        canary_k.compute(runs, audit)


def test_b5_audit_blocked_but_runs_not_is_an_error():
    runs = [row("G-1", 0), row("B-1", 0, gateway_blocked=False)]
    audit = audit_of(rec("G-1-0"), blocked_rec("B-1-0"))
    with pytest.raises(canary_k.CanaryKError, match="gateway_blocked"):
        canary_k.compute(runs, audit)


def test_b5_runs_blocked_but_audit_not_is_an_error():
    runs = [row("G-1", 0), row("G-2", 0, gateway_blocked=True)]
    audit = audit_of(rec("G-1-0"), rec("G-2-0"))
    with pytest.raises(canary_k.CanaryKError, match="gateway_blocked"):
        canary_k.compute(runs, audit)


def test_b6_blocked_without_blocked_by_is_an_error():
    runs = [row("G-1", 0), row("B-1", 0, gateway_blocked=True)]
    audit = audit_of(rec("G-1-0"), blocked_rec("B-1-0", blocked_by=None))
    with pytest.raises(canary_k.CanaryKError, match="blocked_by 없음"):
        canary_k.compute(runs, audit)


def test_b7_blocked_last_action_not_block_is_an_error():
    runs = [row("G-1", 0), row("B-1", 0, gateway_blocked=True)]
    dets = BLOCK + [{"detector": "pii_mask", "action": "allow", "ms": 0.01}]
    audit = audit_of(rec("G-1-0"), blocked_rec("B-1-0", detectors=dets))
    with pytest.raises(canary_k.CanaryKError, match="action"):
        canary_k.compute(runs, audit)


def test_b8_blocked_with_canary_observe_is_an_error():
    runs = [row("G-1", 0), row("B-1", 0, gateway_blocked=True)]
    audit = audit_of(rec("G-1-0"), blocked_rec("B-1-0", detectors=ON + BLOCK))
    with pytest.raises(canary_k.CanaryKError, match="canary_observe"):
        canary_k.compute(runs, audit)


def test_b9_all_blocked_is_an_error():
    runs = [row("B-1", 0, gateway_blocked=True), row("B-2", 0, gateway_blocked=True)]
    audit = audit_of(blocked_rec("B-1-0"), blocked_rec("B-2-0"))
    with pytest.raises(canary_k.CanaryKError, match="관측 요청 0건"):
        canary_k.compute(runs, audit)


def test_b10_runs_error_is_an_error():
    runs = [row("G-1", 0), row("G-2", 0, error="HTTP 500")]
    audit = audit_of(rec("G-1-0"), rec("G-2-0"))
    with pytest.raises(canary_k.CanaryKError, match="error"):
        canary_k.compute(runs, audit)


def test_b10_audit_status_500_is_an_error():
    runs = [row("G-1", 0), row("G-2", 0)]
    audit = audit_of(rec("G-1-0"), rec("G-2-0", status=500))
    with pytest.raises(canary_k.CanaryKError, match="status"):
        canary_k.compute(runs, audit)


def test_b11_runs_without_gateway_blocked_key_is_an_error():
    r = row("G-1", 0)
    del r["gateway_blocked"]
    with pytest.raises(canary_k.CanaryKError, match="gateway_blocked"):
        canary_k.compute([r], audit_of(rec("G-1-0")))


def test_b12_items_total_counts_observed_plus_blocked(tmp_path, capsys):
    out = run_main(tmp_path, 100, 0, capsys, n_blocked=1)
    assert "문항 합계 100" in out
    assert "문항 수가 100이 아니다" not in out
