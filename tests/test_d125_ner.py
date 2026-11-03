"""D-125(PLAN 17단계): NER 평가셋·점수와 탐지 사이드카의 고정 — 게이트웨이 가상환경(onnxruntime 없음)에서 도는 정적 검사.

사이드카 자체(디코더·HTTP 계약·실제 모델)는 `detect/tests/`가 CI의 detect 작업에서 시험한다 — 이 파일은 그 작업이 기대는 고정값(평가셋 바이트·
모델 리비전·해시·의존성 고정·CI 단계)이 몰래 바뀌지 않는지만 본다.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from eval.ner import make_synth, score      # 패키지 경로로 — 이름만으로 import하면 eval/pii의 score와 sys.modules에서 부딪친다

ROOT = Path(__file__).resolve().parents[1]
NER = ROOT / "eval" / "ner"
SYNTH_SHA256 = "ea9792a18df0393505aea09a01833048d9c5150f425098a3e347ed94330d1290"      # D-125 §6


def test_n1_synth_matches_generator_and_schema():
    """N1: 합성 200문장 — 생성기 출력과 바이트까지 같고, 구간이 글자 범위 안·서로 겹치지 않음·종류 셋, 수가 결정과 같다."""
    text = make_synth.render()
    assert (NER / "synth.jsonl").read_text(encoding="utf-8") == text
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == SYNTH_SHA256          # 생성기를 고쳐 다시 만들어도 게이트 셋이 몰래 바뀌지 않게
    rows = [json.loads(x) for x in text.splitlines()]
    assert len(rows) == 200 and len({r["id"] for r in rows}) == 200
    kinds = Counter()
    for r in rows:
        spans = sorted((s["start"], s["end"], s["kind"]) for s in r["spans"])
        for (s0, e0, _), (s1, _, _) in zip(spans, spans[1:]):
            assert e0 <= s1, r["id"]
        for s, e, k in spans:
            assert 0 <= s < e <= len(r["text"]) and k in score.KINDS, r["id"]
            assert r["text"][s:e] == r["text"][s:e].strip(), r["id"]       # 구간 끝에 공백이 없다
            kinds[k] += 1
    assert kinds == {"person": 230, "address": 90, "org": 90}
    assert sum(1 for r in rows if not r["spans"]) == 25


def test_n1_person_spans_exclude_titles_and_particles():
    """N1: 이름 구간 바로 뒤가 호칭·조사여도 구간은 이름 글자만이다(구간 규약). 이름은 사전의 성 + 이름이거나 영문 이름이다."""
    names = {s + g for s in make_synth.SURNAMES for g in make_synth.GIVEN} | set(make_synth.EN_NAMES)
    for line in (NER / "synth.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for s in r["spans"]:
            if s["kind"] == "person":
                assert r["text"][s["start"]:s["end"]] in names, r["id"]


def test_n1_josa_follows_final_sound():
    """N1: 조사는 앞 글자를 읽은 소리의 받침을 따른다 — 숫자는 한자어로 읽는다(152 백오십이 → 로, 150 백오십 → 으로, 1 일 → 로)."""
    cases = {("김민준", "은/는"): "은", ("이수아", "은/는"): "는", ("최철", "으로/로"): "로", ("조지윤", "으로/로"): "으로",
             ("판교역로 152", "으로/로"): "로", ("테헤란로 150", "으로/로"): "으로", ("중앙로 1", "으로/로"): "로",
             ("세종대로 100", "이/가"): "이", ("대학로 1000", "이/가"): "이", ("구미중앙로 2", "이/가"): "가", ("한빛초등학교", "이고/고"): "고"}
    for (prev, pair), want in cases.items():
        assert make_synth.josa(prev, pair) == want, (prev, pair)


def test_n2_score_exact_overlap_char():
    """N2: exact는 시작·끝·종류가 같아야, overlap은 같은 종류로 겹치면 맞힘(정답 하나에 예측 하나), 글자 재현율은 종류와 무관하게 덮은 글자."""
    gold = [{"id": "a", "text": "x" * 40, "spans": [{"kind": "person", "start": 0, "end": 3}, {"kind": "address", "start": 10, "end": 30}]},
            {"id": "b", "text": "y" * 10, "spans": []}]
    pred = [{"id": "a", "spans": [{"kind": "person", "start": 0, "end": 3}, {"kind": "address", "start": 10, "end": 20},
                                  {"kind": "address", "start": 12, "end": 14}, {"kind": "org", "start": 20, "end": 25}]},
            {"id": "b", "spans": [{"kind": "person", "start": 0, "end": 2}, {"kind": "phone", "start": 3, "end": 5}]}]
    r = score.score(gold, pred)
    assert r["person"]["exact"]["tp"] == 1 and r["person"]["exact"]["pred"] == 2 and r["person"]["exact"]["gold"] == 1
    assert r["address"]["exact"]["tp"] == 0 and r["address"]["overlap"]["tp"] == 1 and r["address"]["exact"]["pred"] == 2
    assert r["address"]["char_recall"] == 15 / 20           # 10..20(주소) + 20..25(직장)이 덮는다 — 종류 무관
    assert r["all"]["exact"]["tp"] == 1 and r["all"]["exact"]["pred"] == 5 and r["all"]["exact"]["gold"] == 2    # phone은 세지 않는다
    assert abs(r["all"]["exact"]["f1"] - 2 * (1 / 5) * (1 / 2) / (1 / 5 + 1 / 2)) < 1e-12
    try:
        score.score(gold, pred[:1])
    except ValueError as exc:
        assert "b" in str(exc)
    else:
        raise AssertionError("예측이 빠진 id를 잡지 못했다")


KDPII_SHA256 = "31974906ec96b4fb3fa308981ad62f7b9bf766b80e5ea20679a9edfcac804cfb"      # D-125 §6 — build_kdpii.py가 고정 원본에서 만든 파일
# D-125 §6에서 잰 것 — 바꾸면 그 숫자는 더는 이 파일들의 숫자가 아니다. 결정을 먼저 고친다
MEASURED = {"veil-ko-lite-int8": ("a8343030ef774ad78d6f0481a6877a971cef759d", "35f8fd66a328b32b67b79f93a4c29d790dddaa8f094a165efc095ef5e312194d"),
            "atonlee-small-int8": ("1e75c01e707232401883cf364151bbe2e560c708", "53cd2da73867d0a66ea2bec70b582d164115803788438bd63fd8a9ed365868e7")}
REQUIREMENTS = ["fastapi==0.141.1", "uvicorn==0.52.0", "onnxruntime==1.31.1", "tokenizers==0.23.3", "numpy==2.5.4"]


def test_n3_kdpii_set_is_pinned():
    """N3: KDPII 셋은 원본(고정 리비전·SHA-256)에서 결정적으로 옮긴 파일 그대로다 — 행·종류별 수가 결정과 같고 구간이 글자 범위 안이다."""
    raw = (NER / "kdpii_test.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KDPII_SHA256
    rows = [json.loads(x) for x in raw.decode("utf-8").splitlines()]
    assert len(rows) == 4799 and len({r["id"] for r in rows}) == 4799
    assert Counter(s["kind"] for r in rows for s in r["spans"]) == {"org": 467, "person": 274, "address": 208}
    assert all(0 <= s["start"] < s["end"] <= len(r["text"]) for r in rows for s in r["spans"])
    assert (NER / "SOURCES.md").exists()


def test_n6_sidecar_pins():
    """N6: 사이드카가 기대는 고정값 — 모델은 커밋 SHA 리비전과 파일 SHA-256, 의존성은 정확한 버전, 이미지는 접근 로그를 끄고, CI는 x86에서 F1·지연을 잰다."""
    models = json.loads((ROOT / "detect" / "models.json").read_text(encoding="utf-8"))
    for name, m in models.items():
        if m.get("task") == "injection":           # 인젝션 분류기(D-127)의 고정값은 tests/test_d127_guard.py가 본다
            continue
        assert re.fullmatch(r"[0-9a-f]{40}", m["revision"]), name
        assert m["onnx"] in m["files"] and {"tokenizer.json", "config.json"} <= set(m["files"]), name
        assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in m["files"].values()), name
        assert set(m["kinds"].values()) <= set(score.KINDS), name
    for name, (revision, onnx) in MEASURED.items():
        assert models[name]["revision"] == revision and models[name]["files"][models[name]["onnx"]] == onnx, name
    reqs = [x for x in (ROOT / "detect" / "requirements.txt").read_text().splitlines() if x and not x.startswith("#")]
    assert reqs == REQUIREMENTS
    docker = (ROOT / "detect" / "Dockerfile").read_text()
    assert "--no-access-log" in docker and "USER 10001" in docker and re.search(r"FROM python:\S+@sha256:[0-9a-f]{64}", docker)
    ci = (ROOT / ".github" / "workflows" / "detect.yml").read_text()
    for step in ("detect/requirements.txt", "python -m detect.fetch", "-m pytest -q", "detect/tests", "python -m detect.evaluate --model veil-ko-lite-int8",
                 "--threads 4 --github", "--threads 2 --github", "docker build -f detect/Dockerfile"):
        assert step in ci, step
    assert re.findall(r"uses: (\S+)", ci) and all(re.search(r"@[0-9a-f]{40}$", u) for u in re.findall(r"uses: (\S+)", ci))   # 액션은 SHA로
