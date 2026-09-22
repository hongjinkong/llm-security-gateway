"""D-062 빚 6-a — `scripts/cluster_ci.py` 군집 부트스트랩 CI.

**합성 자료만 쓴다.** 실제 리포트는 열지 않는다(실제 경로 확인은 C4의 별도 단계).
사전 등록된 무효 조건 C1~C4와, 등록된 변이 7종이 **검출되는지**를 이 파일이 맡는다.

변이 대조표 (D-062 8절)
  1 출력 재표집            -> C4 rho=1 (폭이 Wilson과 같아짐)
  2 비복원추출             -> 폭 > 0
  3 군집 안에서 다시 뽑기   -> C4 rho=1 (좁아짐)
  4 percentile 뒤바꿈       -> 하한 <= 점추정 <= 상한
  5 짝 깨기                -> 상수차이 자료에서 짝 CI 폭이 거의 0
  6 정규화 누락            -> 공통 군집 수
  7 B=10                   -> 서로 다른 seed의 경계 일치
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cluster_ci as cc  # noqa: E402

DET = "promptinject.AttackRogueString"
MSG = cc.MSG


def _prompt(text: str) -> dict:
    return {"turns": [{"role": "user", "content": {"text": text, "lang": "en"}}], "notes": None}


def write_report(path: Path, rows, gen_name: str, probe: str = "p.Hijack") -> Path:
    """rows: (프롬프트 본문, 차단 출력 수, 점수 목록). 차단 출력이 앞쪽에 온다."""
    recs = []
    for seq, (text, n_blocked, scores) in enumerate(rows):
        outs = [{"text": MSG} if i < n_blocked else {"text": f"r{seq}-{i}"}
                for i in range(len(scores))]
        recs.append({"entry_type": "attempt", "status": 2, "seq": seq,
                     "probe_classname": probe,
                     "prompt": _prompt(text.replace("<G>", gen_name)),
                     "outputs": outs, "detector_results": {DET: scores}})
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                    encoding="utf-8")
    return path


def rho1(m: int, n_pos: int, size: int = 10):
    """rho=1 — 프롬프트마다 10개가 전부 같은 운명. 빚 3에서 실제로 관측된 모양이다."""
    return [(size, size)] * n_pos + [(0, size)] * (m - n_pos)


def rho0(m: int, p: float, seed: int, size: int = 10):
    """rho=0 — 출력이 서로 독립."""
    rng = random.Random(seed)
    return [(sum(rng.random() < p for _ in range(size)), size) for _ in range(m)]


def width(ci):
    return ci[1] - ci[0]


# ------------------------------------------------------------------ 분자 정의 (C1의 뿌리)

def test_존재기반_판정기에서_성공수는_fails와_같다(tmp_path):
    """차단 응답은 로그 문구라 rogue string이 없다 -> 점수 0. fails에 애초에 안 들어간다.
    matched_baseline 의 fails-blocked 를 그대로 쓰면 음수가 난다."""
    rows = [("q1", 6, [0, 0, 0, 0, 0, 0, 1, 1, 1, 0])]
    st = cc.collect(write_report(tmp_path / "r.jsonl", rows, "g"), DET, None)
    (k,) = st.values()
    assert (k["fails"], k["blocked"], k["fb"]) == (3, 6, 0)
    assert cc.clusters(st, st.keys(), "asr") == [(3, 10)]
    assert cc.clusters(st, st.keys(), "blocked") == [(6, 10)]


def test_부재기반_판정기에서는_차단분이_빠진다(tmp_path):
    """부재 기반이면 차단 응답이 '완화 문구 없음'으로 실패에 잡힌다. 그때는 빼야 한다."""
    rows = [("q1", 6, [1, 1, 1, 1, 1, 1, 1, 0, 0, 0])]
    st = cc.collect(write_report(tmp_path / "r.jsonl", rows, "g"), DET, None)
    (k,) = st.values()
    assert (k["fails"], k["blocked"], k["fb"]) == (7, 6, 6)
    assert cc.clusters(st, st.keys(), "asr") == [(1, 10)]


# ------------------------------------------------------------------ 변이 6 — 정규화

def test_변이6_제너레이터_이름을_정규화해야_두_팔이_짝지어진다(tmp_path):
    rows = [(f"act as <G> now q{i}", 0, [0] * 10) for i in range(5)]
    a = cc.collect(write_report(tmp_path / "a.jsonl", rows, "target-anythingllm"),
                   DET, "target-anythingllm")
    b = cc.collect(write_report(tmp_path / "b.jsonl", rows, "gateway-anythingllm"),
                   DET, "gateway-anythingllm")
    assert len(set(a) & set(b)) == 5

    a2 = cc.collect(write_report(tmp_path / "a.jsonl", rows, "target-anythingllm"), DET, None)
    b2 = cc.collect(write_report(tmp_path / "b.jsonl", rows, "gateway-anythingllm"), DET, None)
    assert len(set(a2) & set(b2)) == 0, "정규화를 빠뜨리면 군집 수가 달라진다"


# ------------------------------------------------------------------ C2

def test_c2_군집별_출력수의_합이_총출력수와_같다(tmp_path):
    rows = [(f"q{i}", 0, [0] * 10) for i in range(7)]
    st = cc.collect(write_report(tmp_path / "r.jsonl", rows, "g"), DET, None)
    cl = cc.clusters(st, st.keys(), "asr")
    assert len(cl) == 7
    assert sum(n for _, n in cl) == 70


def test_같은_프롬프트는_프로브와_attempt가_달라도_한_군집(tmp_path):
    a = write_report(tmp_path / "a.jsonl", [("same", 0, [1] * 10)] * 2, "g")
    b = write_report(tmp_path / "b.jsonl", [("same", 0, [0] * 10)], "g", "p.Other")
    a.write_text(a.read_text() + b.read_text())
    st = cc.collect(a, DET, None)
    assert len(st) == 1
    assert cc.totals(cc.clusters(st, st, "asr")) == (20, 30)
    assert next(iter(st.values()))["attempts"] == 3


def test_군집_순서는_입력_순서와_무관하다():
    st = {"b": {"n": 10, "fails": 8, "fb": 0},
          "a": {"n": 20, "fails": 2, "fb": 0}}
    assert cc.clusters(st, ["b", "a"], "asr") == cc.clusters(st, ["a", "b"], "asr")


# ------------------------------------------------------------------ 변이 4 — percentile

def test_변이4_하한이_상한보다_크지_않다():
    cl = rho1(200, 100)
    ci = cc.boot_ratio_ci(cl, B=2000, seed=1)
    assert ci[0] <= cc.ratio(cl) <= ci[1]
    assert ci[0] < ci[1]


# ------------------------------------------------------------------ 변이 2 — 복원추출

def test_변이2_CI_폭이_0이_아니다():
    ci = cc.boot_ratio_ci(rho1(200, 100), B=2000, seed=1)
    assert width(ci) > 0.01, "비복원으로 뽑으면 매번 같은 표본이라 폭이 0으로 수렴한다"


# ------------------------------------------------------------------ C3 / C4 — 변이 1, 3

def test_c3_군집CI가_Wilson보다_넓다():
    cl = rho1(200, 100)
    k, n = cc.totals(cl)
    assert width(cc.boot_ratio_ci(cl, B=5000, seed=1)) >= width(cc.wilson(k, n))


def test_c4_rho1_폭이_Wilson의_루트10배_안팎이다():
    """한 프롬프트의 10개가 전부 같으면 실효 표본은 1/10이다 -> 폭은 sqrt(10)배."""
    cl = rho1(200, 100)
    k, n = cc.totals(cl)
    got = width(cc.boot_ratio_ci(cl, B=10000, seed=cc.SEED_DEFAULT))
    want = width(cc.wilson(k, n)) * 10 ** 0.5
    assert abs(got - want) / want <= 0.10, f"{got=} {want=}"


def test_c4_rho0_은_Wilson과_거의_같다():
    """출력이 독립이면 군집 보정이 할 일이 없다. 0.3%p 안."""
    cl = rho0(500, 0.5, seed=7)
    k, n = cc.totals(cl)
    got = cc.boot_ratio_ci(cl, B=10000, seed=cc.SEED_DEFAULT)
    want = cc.wilson(k, n)
    assert abs(got[0] - want[0]) <= 0.003 and abs(got[1] - want[1]) <= 0.003, f"{got=} {want=}"


@pytest.mark.parametrize("correlated", [False, True])
def test_c4_JSONL_집계경로에서도_두_극단을_재현한다(tmp_path, correlated):
    expected = rho1(200, 100) if correlated else rho0(500, 0.5, seed=7)
    rows = [(f"q{i}", 0, [1] * k + [0] * (n - k)) for i, (k, n) in enumerate(expected)]
    st = cc.collect(write_report(tmp_path / "control.jsonl", rows, "g"), DET, None)
    cl = cc.clusters(st, st, "asr")
    assert sorted(cl) == sorted(expected)
    got = cc.boot_ratio_ci(cl)
    w = cc.wilson(*cc.totals(cl))
    if correlated:
        want = width(w) * 10 ** 0.5
        assert abs(width(got) - want) / want <= 0.10
    else:
        assert max(abs(got[i] - w[i]) for i in (0, 1)) <= 0.003


# ------------------------------------------------------------------ 변이 5 — 짝

def test_변이5_짝지은_차이는_상수차이_자료에서_폭이_거의_0이다():
    """모든 프롬프트에서 차이가 정확히 -0.5면, 짝을 유지하는 한 어떤 재표집에서도 -0.5다."""
    pairs = [((10, 10), (5, 10))] * 100 + [((6, 10), (1, 10))] * 100
    ci = cc.boot_paired_diff_ci(pairs, B=5000, seed=1)
    assert width(ci) < 1e-9, f"짝이 깨졌다: {ci}"
    assert abs(ci[0] - (-0.5)) < 1e-9


def test_변이5_대조_비짝으로_뽑으면_같은_자료에서도_폭이_생긴다():
    pairs = [((10, 10), (5, 10))] * 100 + [((6, 10), (1, 10))] * 100
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    assert width(cc.boot_unpaired_diff_ci(a, b, B=5000, seed=1)) > 0.01


# ------------------------------------------------------------------ 변이 7 — B

def test_변이7_B가_충분하면_다른_seed에서도_경계가_거의_같다():
    cl = rho1(200, 100)
    x = cc.boot_ratio_ci(cl, B=cc.B_DEFAULT, seed=cc.SEED_DEFAULT)
    y = cc.boot_ratio_ci(cl, B=cc.B_DEFAULT, seed=cc.SEED_DEFAULT + 1)
    assert abs(x[0] - y[0]) <= 0.003 and abs(x[1] - y[1]) <= 0.003, f"{x=} {y=}"


# ------------------------------------------------------------------ DEFF

def test_deff는_폭의_제곱비다():
    assert cc.deff((0.0, 0.2), (0.0, 0.1)) == pytest.approx(4.0)


# ------------------------------------------------------------------ main() — C1~C4

import subprocess  # noqa: E402

SCRIPT = ROOT / "scripts" / "cluster_ci.py"


def _two_arms(tmp_path: Path, n_prompts: int = 100, n_blocked: int = 60,
              spread: str = "cluster"):
    """공통 프롬프트 두 팔. +룰이 앞쪽 n_blocked개를 전건차단한다.

    spread="cluster" — 프롬프트마다 10개가 거의 같은 운명(전건성공/전건실패). 빚 3에서
      실제로 관측된 모양이다(전건통과 81 / 전건차단 354 / **부분차단 0**). 군집 간
      변동이 크므로 군집 CI가 Wilson보다 넓어야 한다.
    spread="flat" — 프롬프트마다 성공 수가 5~8로 고르게 묶여 있다. 군집 간 변동이
      이항분포가 예상하는 것보다 **작다**(과소분산 = rho<0). D-062 C3이 "rho<0이 아닌 한
      넓어져야 한다"고 적어 둔 바로 그 경우다.
    """
    base_rows, rule_rows = [], []
    for i in range(n_prompts):
        text = f"act as <G> attack {i}"
        nb = (10 if i % 4 < 3 else 0) if spread == "cluster" else 5 + (i % 4)
        base_rows.append((text, 0, [1 if j < nb else 0 for j in range(10)]))
        if i < n_blocked:
            rule_rows.append((text, 10, [0] * 10))
        else:
            nr = (10 if i % 5 < 2 else 0) if spread == "cluster" else i % 5
            rule_rows.append((text, 0, [1 if j < nr else 0 for j in range(10)]))
    return (write_report(tmp_path / "b.jsonl", base_rows, "target-anythingllm"),
            write_report(tmp_path / "r.jsonl", rule_rows, "gateway-anythingllm"))


def _run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_main_합성자료는_C1에_걸려_exit2다(tmp_path):
    """EXPECTED는 실제 promptinject 산출물의 정수쌍이다. 다른 자료면 반드시 걸려야 한다."""
    b, r = _two_arms(tmp_path)
    p = _run(["--base", str(b), "--rule", str(r), "-B", "500"])
    assert p.returncode == 2, p.stdout
    assert "C1" in p.stdout and "숫자를 내지 않는다" in p.stdout


def test_main_no_c1이면_끝까지_돈다(tmp_path):
    b, r = _two_arms(tmp_path)
    p = _run(["--base", str(b), "--rule", str(r), "-B", "2000", "--no-c1"])
    assert p.returncode == 0, p.stdout + p.stderr
    assert "전건통과 40 / 전건차단 60 / 부분차단 0" in p.stdout
    assert "검정 1" in p.stdout and "검정 2" in p.stdout
    assert "Σ(프롬프트별 출력)=총 출력: 일치" in p.stdout
    assert "★C3" not in p.stdout


def test_main_C4_양성대조_두_극단이_통과로_찍힌다(tmp_path):
    b, r = _two_arms(tmp_path)
    p = _run(["--base", str(b), "--rule", str(r), "-B", "4000", "--no-c1"])
    body = [l for l in p.stdout.splitlines() if l.startswith("  rho=")]
    assert len(body) == 2, p.stdout
    assert all("통과" in l and "★실패" not in l for l in body), body


def test_main_과소분산이면_C3이_발동하고_숫자를_내지_않는다(tmp_path):
    """**도구가 걸러 주는 게 맞는 동작이다.** 군집 간 변동이 이항분포보다 작으면
    (rho<0) 군집 CI가 Wilson보다 좁아진다. D-062 C3이 그 경우를 미리 적어 두었다.

    C3은 사전 등록된 무효 조건이므로 고치지 않는다(D-049). 여기서는 그 동작을 고정한다.
    실제 promptinject 자료는 전건통과/전건차단이라 정반대(과대분산) 쪽이다.
    """
    b, r = _two_arms(tmp_path, spread="flat")
    p = _run(["--base", str(b), "--rule", str(r), "-B", "2000", "--no-c1"])
    assert p.returncode == 2, p.stdout
    assert "C3" in p.stdout and "숫자를 내지 않는다" in p.stdout
    assert "## 단일 비율" not in p.stdout, "무효인데 숫자를 찍었다"
