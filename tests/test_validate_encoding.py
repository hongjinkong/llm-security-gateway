"""D-068: detect partial or mismatched overnight encoding reports."""
import json
from pathlib import Path

from scripts import validate_encoding


def make_report(
    path: Path,
    name: str,
    *,
    missing_last: bool = False,
    bad_eval: bool = False,
    drift: bool = False,
    null_score: bool = False,
) -> None:
    rows = [
        {"entry_type": "start_run setup", "reporting.report_prefix": name,
         "run.generations": 10, "run.soft_probe_prompt_cap": 256,
         "run.seed": 20260819},
        {"entry_type": "init", "garak_version": "0.15.1"},
    ]
    for probe in validate_encoding.PROBES:
        for seq in range(256):
            if missing_last and probe == validate_encoding.PROBES[-1] and seq == 255:
                continue
            scores = [0.0] * 10
            if null_score and probe == validate_encoding.PROBES[0] and seq == 0:
                scores[0] = None
            prompt = f"{probe}-{seq}"
            if drift and probe == validate_encoding.PROBES[0] and seq == 0:
                prompt += "-changed"
            rows.append({
                "entry_type": "attempt", "status": 2,
                "probe_classname": probe, "seq": seq, "prompt": prompt,
                "outputs": [{"text": "model response"} for _ in range(10)],
                "detector_results": {
                    "encoding.DecodeMatch": list(scores),
                    "encoding.DecodeApprox": list(scores),
                },
            })
        for detector in validate_encoding.DETECTORS:
            rows.append({
                "entry_type": "eval", "probe": probe, "detector": detector,
                "fails": 1 if bad_eval and probe == validate_encoding.PROBES[0] else 0,
                "total_evaluated": 2560,
            })
    rows.append({"entry_type": "completion"})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_valid_reports_and_equal_prompts_pass(tmp_path):
    base = tmp_path / "base.jsonl"
    rule = tmp_path / "rule.jsonl"
    make_report(base, "base")
    make_report(rule, "rule")
    assert validate_encoding.main([
        "--report", str(rule), "--name", "rule",
        "--peer", str(base), "--peer-name", "base",
    ]) == 0


def test_partial_report_fails_closed(tmp_path):
    path = tmp_path / "partial.jsonl"
    make_report(path, "partial", missing_last=True)
    assert validate_encoding.main(["--report", str(path), "--name", "partial"]) == 2


def test_eval_disagreement_fails_closed(tmp_path):
    path = tmp_path / "wrong-eval.jsonl"
    make_report(path, "wrong-eval", bad_eval=True)
    assert validate_encoding.main(["--report", str(path), "--name", "wrong-eval"]) == 2


def test_different_prompts_in_two_arms_fail_closed(tmp_path):
    base = tmp_path / "base.jsonl"
    rule = tmp_path / "rule.jsonl"
    make_report(base, "base")
    make_report(rule, "rule", drift=True)
    assert validate_encoding.main([
        "--report", str(rule), "--name", "rule",
        "--peer", str(base), "--peer-name", "base",
    ]) == 2


def test_null_detector_score_fails_closed(tmp_path):
    path = tmp_path / "null.jsonl"
    make_report(path, "null", null_score=True)
    assert validate_encoding.main(["--report", str(path), "--name", "null"]) == 2
