"""D-090 S2 도구 — `scripts/d090_replay_dan_sampling.py`(순서·치환)와 `scripts/d090_compare.py`(대조·판정).

재현 스크립트의 garak 부분은 이미지 안에서만 돈다. 여기서는 garak 없이 시험할 수 있는 것만 본다:
전역 random을 쓰는 순서(seed → hint → 앞 프로브 → [B: backoff] → DanInTheWild), `{generator.name}` 치환,
비교 도구의 정상·불일치·길이 다름·반복 불일치·입력 오류. 실제 리포트·garak 자료는 쓰지 않는다.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import d090_compare as cmp  # noqa: E402
import d090_replay_dan_sampling as rp  # noqa: E402

N = 6   # 합성 자료: DanInTheWild 프롬프트 6개


# ---- 재현 스크립트: 순서와 치환 -------------------------------------------------

class FakeProbe:
    def __init__(self, name: str):
        self.name = name
        self.prompts = [f"p{i}" for i in range(20)]
        if name == rp.DAN_ITW:   # DanInTheWild처럼 적재 때 전역 random으로 자른다
            for i in sorted(random.sample(range(20), 20 - N), reverse=True):
                del self.prompts[i]


def replay(variant: str, pre=rp.PRE_PROBES):
    loaded: list[str] = []

    def load(name):
        loaded.append(name)
        return FakeProbe(name)

    probe, wait, trace = rp.run_replay(
        variant=variant, seed=rp.SEED, load_probe=load,
        hint=lambda: random.random(),
        backoff_retry_once=lambda: random.uniform(0, 1),
        pre_probes=pre,
    )
    return probe, wait, trace, loaded


def test_variant_a_order():
    probe, wait, trace, loaded = replay("A")
    assert trace == ["seed", "hint", *rp.PRE_PROBES, rp.DAN_ITW]
    assert loaded == [*rp.PRE_PROBES, rp.DAN_ITW]
    assert wait is None


def test_variant_b_inserts_backoff_right_after_ranti():
    _, wait, trace, _ = replay("B")
    i = trace.index(rp.RANTI)
    assert trace[i + 1] == "backoff"
    assert trace[i + 2] == rp.PRE_PROBES[rp.PRE_PROBES.index(rp.RANTI) + 1]
    assert trace[-1] == rp.DAN_ITW
    assert 0 <= wait <= 1


def test_seed_then_hint_reproduces_direct_sampling():
    """run_replay가 seed를 넣고 hint 한 번만 쓴 상태로 표집하는지 — 직접 계산과 같아야 한다."""
    probe, *_ = replay("A")
    random.seed(rp.SEED)
    random.random()
    expected = [f"p{i}" for i in range(20)]
    for i in sorted(random.sample(range(20), 20 - N), reverse=True):
        del expected[i]
    assert probe.prompts == expected


def test_variant_b_shifts_sampling():
    a, *_ = replay("A")
    b, *_ = replay("B")
    assert a.prompts != b.prompts


def test_repeated_replay_is_identical():
    assert replay("A")[0].prompts == replay("A")[0].prompts
    assert replay("B")[0].prompts == replay("B")[0].prompts


def test_variant_b_requires_ranti():
    with pytest.raises(ValueError):
        replay("B", pre=tuple(p for p in rp.PRE_PROBES if p != rp.RANTI))


def test_unknown_variant():
    with pytest.raises(ValueError):
        replay("C")


def test_format_like_probe():
    out = rp.format_like_probe(["act as {generator.name} now", "keep {braces} and \\\"quotes\\\""], "target-x")
    assert out == ["act as target-x now", "keep {braces} and \\\"quotes\\\""]


# ---- 비교 도구 ------------------------------------------------------------------

def texts(tag: str) -> list[str]:
    return [f"{tag}-{i}" for i in range(N)]


M_TEXTS = texts("m")
N_TEXTS = M_TEXTS[:4] + ["n-4", "n-5"]        # 끝쪽 2개만 다르다


def report(path: Path, prompts: list[str], *, extra: list[dict] | None = None) -> Path:
    rows: list[dict] = [{"entry_type": "start_run setup"}]
    for seq, t in enumerate(prompts):
        rows.append({"entry_type": "attempt", "status": 1, "probe_classname": cmp.PROBE, "seq": seq})
        rows.append({"entry_type": "attempt", "status": 2, "probe_classname": cmp.PROBE, "seq": seq,
                     "prompt": {"turns": [{"role": "user", "content": {"text": t, "lang": "en"}}], "notes": None}})
    rows.append({"entry_type": "attempt", "status": 2, "probe_classname": "dan.DUDE", "seq": 0,
                 "prompt": {"turns": [{"role": "user", "content": {"text": "other probe"}}]}})
    rows += extra or []
    rows.append({"entry_type": "completion"})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def replay_file(path: Path, variant: str, prompts: list[str], *, wait=None, **over) -> Path:
    data = {"variant": variant, "seed": rp.SEED, "garak_version": cmp.GARAK_VERSION,
            "jitter_wait": wait if variant == "B" else None,
            "prompt_sha256": [rp.text_sha256(t) for t in prompts]}
    data.update(over)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run(tmp: Path, capsys, *, a1=M_TEXTS, a2=M_TEXTS, b1=N_TEXTS, b2=N_TEXTS, wait=0.5,
        m_report=None, a_variant="A", n_a=2) -> tuple[int, str, str]:
    m = m_report or report(tmp / "m.jsonl", M_TEXTS)
    n = report(tmp / "n.jsonl", N_TEXTS)
    args = ["--m", str(m), "--n", str(n), "--expected-n", str(N)]
    for i, t in enumerate((a1, a2)[:n_a], 1):
        args += ["--a", str(replay_file(tmp / f"a{i}.json", a_variant, t))]
    for i, t in enumerate((b1, b2), 1):
        args += ["--b", str(replay_file(tmp / f"b{i}.json", "B", t, wait=wait))]
    code = cmp.main(args)
    out, err = capsys.readouterr()
    return code, out, err


def test_h1_consistent(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys)
    assert code == 0
    assert "S2: H1과 일치" in out
    assert "M과 N이 다른 seq 2개: [4, 5]" in out
    assert f"| A1 | `{tmp_path / 'a1.json'}` | {N} | {N}/{N} | 4/{N} |" in out
    assert "모두 0.45 이상 0.55 미만: 예" in out


def test_b_mismatch_rejects_h1(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, b1=M_TEXTS, b2=M_TEXTS)
    assert code == 0
    assert "H1 기각" in out


def test_a_mismatch_is_undecidable(tmp_path, capsys):
    off = M_TEXTS[:5] + ["x-5"]
    code, out, _ = run(tmp_path, capsys, a1=off, a2=off)
    assert code == 0
    assert "판단 불가 — 변형 A가 M과" in out


def test_length_difference_is_not_full_match(tmp_path, capsys):
    short = M_TEXTS[:-1]
    code, out, _ = run(tmp_path, capsys, a1=short, a2=short)
    assert code == 0
    assert "판단 불가 — 변형 A가 M과" in out
    assert f"| A1 | `{tmp_path / 'a1.json'}` | {N - 1} |" in out


def test_repeat_mismatch_is_undecidable(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, b2=M_TEXTS)
    assert code == 0
    assert "판단 불가 — 같은 변형의 반복이" in out


def test_jitter_out_of_range_does_not_change_verdict(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, wait=0.7)
    assert code == 0
    assert "모두 0.45 이상 0.55 미만: 아니오" in out
    assert "S2: H1과 일치" in out


def test_duplicate_seq_is_input_error(tmp_path, capsys):
    dup = {"entry_type": "attempt", "status": 2, "probe_classname": cmp.PROBE, "seq": 0,
           "prompt": {"turns": [{"role": "user", "content": {"text": "again"}}]}}
    code, _, err = run(tmp_path, capsys, m_report=report(tmp_path / "m.jsonl", M_TEXTS, extra=[dup]))
    assert code == 2
    assert "seq 0 중복" in err


def test_missing_seq_is_input_error(tmp_path, capsys):
    m = report(tmp_path / "m.jsonl", M_TEXTS)
    lines = [ln for ln in m.read_text(encoding="utf-8").splitlines()
             if not ('"seq": 2' in ln and '"status": 2' in ln and cmp.PROBE in ln)]
    m.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code, _, err = run(tmp_path, capsys, m_report=m)
    assert code == 2
    assert "빠짐없이" in err


def test_wrong_variant_is_input_error(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys, a_variant="B")
    assert code == 2
    assert "변형 'B' (기대 A)" in err


def test_run_count_is_enforced(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys, n_a=1)
    assert code == 2
    assert "재현 2회" in err


def test_expected_n_is_enforced(tmp_path, capsys):
    m = report(tmp_path / "m.jsonl", M_TEXTS)
    n = report(tmp_path / "n.jsonl", N_TEXTS)
    args = ["--m", str(m), "--n", str(n)]
    for i in (1, 2):
        args += ["--a", str(replay_file(tmp_path / f"a{i}.json", "A", M_TEXTS))]
        args += ["--b", str(replay_file(tmp_path / f"b{i}.json", "B", N_TEXTS, wait=0.5))]
    assert cmp.main(args) == 2       # 기본 기대값 256
    assert "기대 256" in capsys.readouterr().err


def test_report_hash_uses_replay_hash():
    """두 도구가 같은 해시 함수를 쓴다 — 리포트 텍스트와 재현 텍스트가 같으면 해시도 같다."""
    assert cmp.text_sha256 is rp.text_sha256
