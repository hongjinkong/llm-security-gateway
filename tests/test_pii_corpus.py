"""PII 평가 코퍼스 게이트(D-115 기준선, D-116에서 목표로 조임, D-117에서 새 종류 7개).

탐지(`patterns.find_all`)를 바꾸면 여기 숫자가 움직인다. 게이트 값을 바꾸려면 DECISIONS에 결정을 먼저 적는다.
목표: 종류마다·전체 오탐 1% 이하(음성 1,200건 중 12건), 검증식·지역이 있는 종류의 재현율 99% 이상 — card·driver·brn·ipv4 전체, rrn·frn은 검증식을 통과하는 값.
rrn·frn 전체 재현율은 측정값이다: 구분자·문맥어 없는 검증식 실패 13자리는 설계상 감사에만 남는다(D-116). crn(주민 꼴 + '법인' 문맥 없음은 rrn)·
passport(구형은 문맥어)·account(문맥어)도 문맥에 달린 측정값(D-117). phone·email·secret 재현율은 목표가 없어 기준선.
"""
import ipaddress
import subprocess
import sys
from collections import Counter
from pathlib import Path

from gateway.detectors.patterns import (
    ACCOUNT_LAYOUTS, DRIVER_REGIONS, PASSPORT_RE, brn_check, crn_check, digits, frn_checksum_ok, luhn_ok, rrn_checksum_ok)

PII = Path(__file__).resolve().parents[1] / "eval" / "pii"
sys.path.insert(0, str(PII))
import make_corpus  # noqa: E402
import score  # noqa: E402

RECALL_MIN = {"rrn": 98, "frn": 95, "passport": 80, "driver": 99, "card": 99, "phone": 100, "email": 100, "secret": 100,
              "brn": 99, "crn": 89, "account": 64, "ipv4": 99}       # 종류마다 양성 100건 중
FP_MAX = dict.fromkeys(score.KINDS, 12)                             # 음성 1,200건 중
FP_ANY_MAX = 12
VALID_RECALL = 0.99                                                  # 검증식을 통과하는 주민·외국인 번호(rrn/ok-*·frn/ok-*)


def test_files_match_generator():
    """E1: 자가 몰래 바뀌지 않는다 — 생성기 출력과 커밋된 파일이 바이트까지 같다. 생성기를 고치면 파일을 다시 쓰고 결정을 적는다."""
    corpus, hard = make_corpus.render()
    assert (PII / "corpus.jsonl").read_text(encoding="utf-8") == corpus
    assert (PII / "hard.jsonl").read_text(encoding="utf-8") == hard


def test_corpus_follows_real_number_rules():
    """E2: 양성은 실제 번호 체계를 지킨다(게이트웨이의 검증식으로 대조), 음성에는 정답 구간이 없다."""
    items = score.load(PII / "corpus.jsonl")
    pos = [x for x in items if x["set"] == "pos"]
    assert len(pos) == 1200 and len(items) - len(pos) == 1200
    assert Counter(x["spans"][0]["kind"] for x in pos) == {k: 100 for k in score.KINDS}
    for x in pos:
        span = x["spans"][0]
        raw = x["text"][span["start"]:span["end"]]
        value, kind = digits(raw), span["kind"]
        if kind == "card":
            assert luhn_ok(value), x["id"]
        if kind in ("rrn", "frn"):
            assert (rrn_checksum_ok if kind == "rrn" else frn_checksum_ok)(value) == x["group"].startswith(f"{kind}/ok"), x["id"]
            assert value[6] in ("1234" if kind == "rrn" else "5678"), x["id"]
        if kind == "brn":
            assert brn_check(value) == int(value[9]), x["id"]
        if kind == "crn":
            assert crn_check(value) == int(value[12]), x["id"]
        if kind == "driver":
            assert value[:2] in DRIVER_REGIONS, x["id"]
        if kind == "passport":
            assert PASSPORT_RE.fullmatch(raw), x["id"]
        if kind == "account":
            assert tuple(map(len, raw.split("-"))) in ACCOUNT_LAYOUTS, x["id"]
        if kind == "ipv4":
            assert ipaddress.IPv4Address(raw).is_global, x["id"]
    assert not any(x["spans"] for x in items if x["set"] == "neg")


def test_gate():
    """E4: 종류별 재현율 하한·오탐 상한."""
    res = score.score(score.load(PII / "corpus.jsonl"))
    for kind in score.KINDS:
        assert res["hit"].get(kind, 0) >= RECALL_MIN[kind], (kind, res["hit"], res["missed"])
        assert res["fp"].get(kind, 0) <= FP_MAX[kind], (kind, res["fp"])
    assert res["fp_any"] <= FP_ANY_MAX, res["fp_any"]
    for kind in ("rrn", "frn"):
        valid = [(h, t) for g, (h, t) in res["groups"].items() if g.startswith(f"{kind}/ok-")]
        assert sum(h for h, _ in valid) >= VALID_RECALL * sum(t for _, t in valid), (kind, valid)


def test_score_script_prints_tables():
    """E3: 점수 스크립트가 종류별·묶음별 표와 어려운 사례 표를 낸다."""
    out = subprocess.run([sys.executable, str(PII / "score.py")], capture_output=True, text=True, check=True).stdout
    assert "| 종류 | 재현율 | 95% 구간 |" in out and "| card | 100/100" in out and "| imei |" in out and "hard-pos-01" in out
    assert "| driver | 100/100" in out and "| network |" in out
