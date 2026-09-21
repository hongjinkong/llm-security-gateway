"""D-061-0: `scripts/matched_baseline.py` — 동기·사전등록 문서를 인자로 받는다.

**왜 이 파일이 생겼나.** 이 스크립트도 D-057(dan)을 위해 쓰였고, 동기 문장과 분기
문구에 dan의 숫자(77.8% / 74.5%)가 박혀 있었다. 다른 프로브에 돌리면 산출물에
**남의 런 문장**이 찍힌다. `rescore_blocking.py`의 문구 결함과 뿌리가 같다(D-061-0 5절).

합성 리포트만 쓴다. 실제 리포트는 열지 않는다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import matched_baseline as mb  # noqa: E402

MSG = mb.MSG
DET = "promptinject.AttackRogueString"


def _prompt(text: str) -> dict:
    return {"turns": [{"role": "user", "content": {"text": text, "lang": "en"}}], "notes": None}


def write_report(path: Path, rows_spec, gen_name: str, probe: str = "p.Hijack") -> Path:
    """rows_spec: (프롬프트 본문, 차단된 출력 수, 점수 목록) 목록."""
    rows = []
    for seq, (text, n_blocked, scores) in enumerate(rows_spec):
        outs = [{"text": MSG} if i < n_blocked else {"text": f"resp{seq}-{i}"}
                for i in range(len(scores))]
        rows.append({"entry_type": "attempt", "status": 2, "seq": seq,
                     "probe_classname": probe,
                     "prompt": _prompt(text.replace("<G>", gen_name)),
                     "outputs": outs, "detector_results": {DET: scores}})
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return path


# ------------------------------------------------------------------ 단위

def test_key_of_제너레이터_이름을_정규화한다():
    """dan 프로브는 제너레이터 이름을 프롬프트 본문에 넣는다(D-057 8절)."""
    a = {"probe_classname": "probes.dan.A", "prompt": _prompt("act as target-anythingllm now")}
    b = {"probe_classname": "probes.dan.A", "prompt": _prompt("act as gateway-anythingllm now")}
    assert mb.key_of(a, "target-anythingllm") == mb.key_of(b, "gateway-anythingllm")


def test_key_of_다른_프롬프트는_다른_키다():
    a = {"probe_classname": "probes.p.X", "prompt": _prompt("질문 하나")}
    b = {"probe_classname": "probes.p.X", "prompt": _prompt("질문 둘")}
    assert mb.key_of(a, None) != mb.key_of(b, None)


def test_key_of_같은_프롬프트라도_프로브가_다르면_다른_키다():
    a = {"probe_classname": "probes.p.X", "prompt": _prompt("같은 질문")}
    b = {"probe_classname": "probes.p.Y", "prompt": _prompt("같은 질문")}
    assert mb.key_of(a, None) != mb.key_of(b, None)


def test_collect_차단과_성공을_따로_센다(tmp_path):
    p = write_report(tmp_path / "r.jsonl", [
        ("<G> 하나", 10, [0.0] * 10),
        ("<G> 둘", 0, [1.0] * 4 + [0.0] * 6),
    ], "target-anythingllm")
    got = mb.collect(p, DET, "target-anythingllm")
    vals = sorted(got.values(), key=lambda d: d["blocked"])
    assert vals[0] == {"n": 10, "fails": 4, "blocked": 0}
    assert vals[1] == {"n": 10, "fails": 0, "blocked": 10}


def test_collect_차단문구를_품은_긴_출력은_차단이_아니다(tmp_path):
    """S1은 전체 일치다. 부분 포함으로 세면 차단 수가 부풀어 짝짓기가 틀어진다."""
    p = write_report(tmp_path / "r.jsonl", [
        ("<G> 하나", 0, [0.0] * 2),
    ], "target-anythingllm")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    rows[0]["outputs"] = [{"text": MSG}, {"text": MSG + " 그리고 덧붙인 문장"}]
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    got = list(mb.collect(p, DET, "target-anythingllm").values())
    assert got[0]["blocked"] == 1


def test_two_prop_같은_비율이면_z가_0이다():
    z, p = mb.two_prop(50, 100, 50, 100)
    assert abs(z) < 1e-12 and p > 0.99


# -------------------------------------------------------------------- CLI

def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "matched_baseline.py"), *args],
                          capture_output=True, text=True)


def _pair(tmp_path: Path, rule_blocked_first: int = 10):
    base = write_report(tmp_path / "base.jsonl", [
        ("<G> 하나", 0, [1.0] * 9 + [0.0]),
        ("<G> 둘", 0, [1.0] * 2 + [0.0] * 8),
    ], "target-anythingllm")
    rule = write_report(tmp_path / "rule.jsonl", [
        ("<G> 하나", rule_blocked_first, [0.0] * 10),
        ("<G> 둘", 0, [1.0] * 2 + [0.0] * 8),
    ], "target-anythingllm")
    return base, rule


ARGS_TAIL = ["--detector", DET,
             "--base-generator-name", "target-anythingllm",
             "--rule-generator-name", "target-anythingllm"]


def test_CLI_둘다_안_넘기면_거부한다(tmp_path):
    base, rule = _pair(tmp_path)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL])
    assert r.returncode != 0


def test_CLI_사전등록_문서를_안_넘기면_거부한다(tmp_path):
    """기본값을 주면 남의 런 번호가 조용히 찍힌다. 반드시 넘기게 한다."""
    base, rule = _pair(tmp_path)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL, "--motive", "검사"])
    assert r.returncode != 0
    assert "registered-in" in r.stderr


def test_CLI_동기를_안_넘기면_거부한다(tmp_path):
    base, rule = _pair(tmp_path)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL, "--registered-in", "D-061-0"])
    assert r.returncode != 0
    assert "motive" in r.stderr


def test_CLI_넘긴_동기가_그대로_찍힌다(tmp_path):
    base, rule = _pair(tmp_path)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL,
              "--registered-in", "D-061-0", "--motive", "빚 3의 자기정합성 판정을 본 뒤에 착안했다"])
    assert r.returncode == 0, r.stderr
    assert "D-061-0" in r.stdout
    assert "빚 3의 자기정합성 판정을 본 뒤에 착안했다" in r.stdout


def test_CLI_남의_런_숫자가_찍히지_않는다(tmp_path):
    """이 결함의 본체. dan의 77.8% / 74.5% 가 pi 산출물에 나오면 안 된다."""
    base, rule = _pair(tmp_path)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL,
              "--registered-in", "D-061-0", "--motive", "합성 데이터 검사"])
    assert r.returncode == 0, r.stderr
    for banned in ("77.8", "74.5", "1번 분기", "2번 분기", "3번 분기", "DanInTheWild", "seed=None"):
        assert banned not in r.stdout, banned


def test_CLI_선택성_지표를_낸다(tmp_path):
    base, rule = _pair(tmp_path)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL,
              "--registered-in", "D-061-0", "--motive", "합성 데이터 검사"])
    assert "부수 지표 — 룰의 선택성" in r.stdout
    assert "룰이 막은 1개 프롬프트의 베이스라인 ASR" in r.stdout
    assert "90.00%" in r.stdout          # 막은 프롬프트의 베이스라인 ASR 9/10
    assert "20.00%" in r.stdout          # 통과시킨 프롬프트의 베이스라인 ASR 2/10


def test_CLI_짝짓기_불일치는_비율과_함께_알린다(tmp_path):
    base = write_report(tmp_path / "base.jsonl", [
        ("하나", 0, [1.0] * 10), ("둘", 0, [1.0] * 10)], "target-anythingllm")
    rule = write_report(tmp_path / "rule.jsonl", [
        ("하나", 10, [0.0] * 10), ("셋", 0, [1.0] * 10)], "target-anythingllm")
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL,
              "--registered-in", "D-061-0", "--motive", "합성 데이터 검사"])
    assert "프롬프트 집합이 완전히 같지 않다" in r.stdout
    assert "공통 비율 1/2 = 50.0%" in r.stdout
    assert "원인을 여기서 단정하지 않는다" in r.stdout
    assert "크래시" not in r.stderr and "Traceback" not in r.stderr
    assert "짝지은 비교를 할 수 없다" in r.stdout
    assert r.returncode == 1


def test_CLI_부분차단이_있으면_경고한다(tmp_path):
    base, rule = _pair(tmp_path, rule_blocked_first=4)
    r = _run(["--base", str(base), "--rule", str(rule), *ARGS_TAIL,
              "--registered-in", "D-061-0", "--motive", "합성 데이터 검사"])
    assert "★ 부분차단이 있다" in r.stdout
