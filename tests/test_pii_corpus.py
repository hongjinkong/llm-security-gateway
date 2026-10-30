"""PII 평가 코퍼스 게이트(D-115 기준선, D-116에서 목표로 조임).

탐지(`patterns.find_all`)를 바꾸면 여기 숫자가 움직인다. 게이트 값을 바꾸려면 DECISIONS에 결정을 먼저 적는다.
목표: 종류마다·전체 오탐 1% 이하(음성 1,000건 중 10건), 체크섬 종류의 재현율 99% 이상 — card 전체, rrn은 검증식을 통과하는 값.
rrn 전체 재현율은 측정값이다: 구분자·문맥어 없는 검증식 실패 13자리는 설계상 감사에만 남는다(D-116). phone·email·secret 재현율은 목표가 없어 기준선.
"""
import subprocess
import sys
from collections import Counter
from pathlib import Path

from gateway.detectors.patterns import digits, luhn_ok, rrn_checksum_ok

PII = Path(__file__).resolve().parents[1] / "eval" / "pii"
sys.path.insert(0, str(PII))
import make_corpus  # noqa: E402
import score  # noqa: E402

RECALL_MIN = {"rrn": 98, "card": 99, "phone": 96, "email": 100, "secret": 100}   # 종류마다 양성 100건 중
FP_MAX = {"rrn": 10, "card": 10, "phone": 10, "email": 10, "secret": 10}        # 음성 1,000건 중
FP_ANY_MAX = 10
RRN_VALID_RECALL = 0.99                                                          # 검증식을 통과하는 주민번호(rrn/ok-*)


def test_files_match_generator():
    """E1: 자가 몰래 바뀌지 않는다 — 생성기 출력과 커밋된 파일이 바이트까지 같다. 생성기를 고치면 파일을 다시 쓰고 결정을 적는다."""
    corpus, hard = make_corpus.render()
    assert (PII / "corpus.jsonl").read_text(encoding="utf-8") == corpus
    assert (PII / "hard.jsonl").read_text(encoding="utf-8") == hard


def test_corpus_follows_real_number_rules():
    """E2: 양성은 실제 번호 체계를 지킨다(게이트웨이의 검증식으로 대조), 음성에는 정답 구간이 없다."""
    items = score.load(PII / "corpus.jsonl")
    pos = [x for x in items if x["set"] == "pos"]
    assert len(pos) == 500 and len(items) - len(pos) == 1000
    assert Counter(x["spans"][0]["kind"] for x in pos) == {k: 100 for k in score.KINDS}
    for x in pos:
        span = x["spans"][0]
        value = digits(x["text"][span["start"]:span["end"]])
        if span["kind"] == "card":
            assert luhn_ok(value), x["id"]
        if span["kind"] == "rrn":
            assert rrn_checksum_ok(value) == x["group"].startswith("rrn/ok"), x["id"]
    assert not any(x["spans"] for x in items if x["set"] == "neg")


def test_gate():
    """E4: 종류별 재현율 하한·오탐 상한."""
    res = score.score(score.load(PII / "corpus.jsonl"))
    for kind in score.KINDS:
        assert res["hit"].get(kind, 0) >= RECALL_MIN[kind], (kind, res["hit"], res["missed"])
        assert res["fp"].get(kind, 0) <= FP_MAX[kind], (kind, res["fp"])
    assert res["fp_any"] <= FP_ANY_MAX, res["fp_any"]
    valid = [(h, t) for g, (h, t) in res["groups"].items() if g.startswith("rrn/ok-")]
    assert sum(h for h, _ in valid) >= RRN_VALID_RECALL * sum(t for _, t in valid), valid


def test_score_script_prints_tables():
    """E3: 점수 스크립트가 종류별·묶음별 표와 어려운 사례 표를 낸다."""
    out = subprocess.run([sys.executable, str(PII / "score.py")], capture_output=True, text=True, check=True).stdout
    assert "| 종류 | 재현율 | 95% 구간 |" in out and "| card | 100/100" in out and "| imei |" in out and "hard-pos-01" in out
