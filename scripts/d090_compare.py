#!/usr/bin/env python3
"""D-090 S2 비교 — 재현 해시를 M·N 리포트의 DanInTheWild 프롬프트와 seq 순서로 대조한다.

M: 2밤 none = 2밤 rule = D-089 rule (D-089 §6에서 400/400 일치). N: D-089 none.
리포트 쪽은 status=2 attempt의 user turn 텍스트를 d090_replay_dan_sampling.text_sha256으로 해시한다.
D-090 §4 판정 중 S2 부분만 낸다. S1(이미지 소스 확인)은 사람이 확인해 따로 적고, 둘을 합쳐 최종 판정한다.

  python3 scripts/d090_compare.py \
    --m results/oa_dan_20260930_01_none.report.jsonl --n results/oa_dan_20261006_01_none.report.jsonl \
    --a results/d090_replay_A_1.json --a results/d090_replay_A_2.json \
    --b results/d090_replay_B_1.json --b results/d090_replay_B_2.json > results/d090_compare.md

종료 코드: 0 비교 완료(판정은 출력에) / 2 입력 오류
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from d090_replay_dan_sampling import SEED, text_sha256

PROBE = "dan.DanInTheWild"
GARAK_VERSION = "0.15.1"
RUNS_PER_VARIANT = 2
JITTER_RANGE = (0.45, 0.55)   # garak.log "for 0.5s"(%.1f 표기) — 보조 관찰, 판정에 쓰지 않는다


class InputError(Exception):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise InputError(message)


def report_hashes(path: Path, probe: str = PROBE) -> list[str]:
    """seq 0..n-1 순서의 user turn 텍스트 해시. seq 중복·빠짐, user turn이 하나가 아니면 입력 오류."""
    require(path.is_file(), f"리포트 없음: {path}")
    by_seq: dict[int, str] = {}
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"{path}:{no}: JSON 파손: {exc}") from exc
        if row.get("entry_type") != "attempt" or row.get("status") != 2 or row.get("probe_classname") != probe:
            continue
        seq = row.get("seq")
        require(isinstance(seq, int), f"{path}:{no}: seq 없음")
        require(seq not in by_seq, f"{path}: seq {seq} 중복")
        turns = (row.get("prompt") or {}).get("turns") or []
        users = [t for t in turns if t.get("role") == "user"]
        require(len(users) == 1, f"{path}: seq {seq} user turn {len(users)}개")
        text = (users[0].get("content") or {}).get("text")
        require(isinstance(text, str), f"{path}: seq {seq} 텍스트 없음")
        by_seq[seq] = text_sha256(text)
    require(bool(by_seq), f"{path}: {probe} status=2 attempt 0개")
    require(sorted(by_seq) == list(range(len(by_seq))), f"{path}: seq가 0부터 빠짐없이 이어지지 않는다")
    return [by_seq[i] for i in range(len(by_seq))]


def load_replay(path: Path, variant: str) -> dict:
    require(path.is_file(), f"재현 결과 없음: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: JSON 파손: {exc}") from exc
    require(data.get("variant") == variant, f"{path}: 변형 {data.get('variant')!r} (기대 {variant})")
    require(data.get("seed") == SEED, f"{path}: seed {data.get('seed')!r} (기대 {SEED})")
    require(data.get("garak_version") == GARAK_VERSION, f"{path}: garak {data.get('garak_version')!r}")
    hashes = data.get("prompt_sha256")
    require(isinstance(hashes, list) and all(isinstance(h, str) for h in hashes), f"{path}: prompt_sha256 없음")
    return data


def matches(a: list[str], b: list[str]) -> int:
    return sum(1 for x, y in zip(a, b) if x == y)


def full(a: list[str], b: list[str]) -> bool:
    return len(a) == len(b) and a == b


def verdict(a_runs: list[list[str]], b_runs: list[list[str]], m: list[str], n: list[str]) -> str:
    """D-090 §4의 S2 부분. 순서: 반복 일치 → A=M → B=N."""
    if any(r != a_runs[0] for r in a_runs) or any(r != b_runs[0] for r in b_runs):
        return "판단 불가 — 같은 변형의 반복이 서로 다르다"
    if not all(full(r, m) for r in a_runs):
        return "판단 불가 — 변형 A가 M과 전부 일치하지 않는다(재현이 실제 실행의 난수 소비를 다 담지 못함)"
    if not all(full(r, n) for r in b_runs):
        return "H1 기각 — 변형 A는 M과 일치하지만 변형 B가 N과 전부 일치하지 않는다"
    return "S2: H1과 일치 — 최종 'H1 확인'은 S1 일치가 함께 필요하다"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--m", type=Path, required=True, help="M 리포트(2밤 none)")
    ap.add_argument("--n", type=Path, required=True, help="N 리포트(D-089 none)")
    ap.add_argument("--a", type=Path, action="append", required=True, help="변형 A 재현 결과(2개)")
    ap.add_argument("--b", type=Path, action="append", required=True, help="변형 B 재현 결과(2개)")
    ap.add_argument("--expected-n", type=int, default=256, help="DanInTheWild 프롬프트 수(D-089 §5 P4)")
    a = ap.parse_args(argv)
    try:
        require(len(a.a) == RUNS_PER_VARIANT and len(a.b) == RUNS_PER_VARIANT,
                f"변형마다 재현 {RUNS_PER_VARIANT}회가 필요하다 (A {len(a.a)}, B {len(a.b)})")
        m = report_hashes(a.m)
        n = report_hashes(a.n)
        require(len(m) == a.expected_n and len(n) == a.expected_n,
                f"리포트 프롬프트 수 M {len(m)}, N {len(n)} (기대 {a.expected_n})")
        a_data = [load_replay(p, "A") for p in a.a]
        b_data = [load_replay(p, "B") for p in a.b]
    except (InputError, OSError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    a_runs = [d["prompt_sha256"] for d in a_data]
    b_runs = [d["prompt_sha256"] for d in b_data]
    total = len(m)
    out = ["# D-090 S2 비교 — DanInTheWild 표집 재현", ""]
    out.append(f"- M `{a.m}`, N `{a.n}`, 프롬프트 {total}개")
    diff_mn = [i for i in range(total) if m[i] != n[i]]
    out.append(f"- M과 N이 다른 seq {len(diff_mn)}개: {diff_mn}")
    out += ["", "| 재현 | 파일 | 수 | M 일치 | N 일치 | jitter 대기값 |", "|---|---|---|---|---|---|"]
    for label, paths, datas in (("A", a.a, a_data), ("B", a.b, b_data)):
        for i, (p, d) in enumerate(zip(paths, datas), 1):
            h = d["prompt_sha256"]
            out.append(f"| {label}{i} | `{p}` | {len(h)} | {matches(h, m)}/{total} | {matches(h, n)}/{total} "
                       f"| {d.get('jitter_wait')} |")
    out.append("")
    meta_keys = ("garak_version", "backoff_version", "python", "soft_probe_prompt_cap", "data_sha256",
                 "data_items", "data_items_nonempty", "generator_name", "formatted_count", "trace")
    for k in meta_keys:
        vals = {json.dumps(d.get(k), ensure_ascii=False) for d in a_data + b_data}
        out.append(f"- {k}: {' / '.join(sorted(vals))}")
    out.append("")
    waits = [d.get("jitter_wait") for d in b_data]
    lo, hi = JITTER_RANGE
    in_range = all(isinstance(w, (int, float)) and lo <= w < hi for w in waits)
    out.append(f"- 보조 관찰(판정에 쓰지 않음): 변형 B jitter {waits}, 모두 {lo} 이상 {hi} 미만: "
               f"{'예' if in_range else '아니오'}")
    out.append("")
    out.append(f"**{verdict(a_runs, b_runs, m, n)}**")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
