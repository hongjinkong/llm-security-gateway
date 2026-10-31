#!/usr/bin/env python3
"""PII 평가 점수(D-115, PLAN 8단계) — 종류별 재현율·오탐률과 Wilson 95% 구간을 마크다운 표로 낸다.

  python3 eval/pii/score.py              # corpus.jsonl 표 + hard.jsonl 사례별 표
  python3 eval/pii/score.py 다른.jsonl    # 같은 형식의 다른 파일

판정은 **가리는 탐지**(`Finding.mask`, D-116)만 센다 — 감사에만 남는 탐지는 값이 상류로 가므로 맞힘이 아니고, 텍스트를 바꾸지 않으므로 오탐도 아니다.
  양성  같은 종류의 가리는 탐지가 정답 구간을 전부 덮으면 맞힘. 일부만 덮으면 값이 새므로 놓침.
  음성  그 종류의 가리는 탐지가 하나라도 있으면 그 종류의 오탐, 아무 종류든 있으면 전체 오탐.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from gateway.detectors.patterns import find_all  # noqa: E402

KINDS = ("rrn", "frn", "passport", "driver", "card", "phone", "email", "secret", "brn", "crn", "account", "ipv4")   # D-117: 새 종류 7개


def load(path: Path) -> list[dict]:
    items = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    for it in items:
        assert all(0 <= s["start"] < s["end"] <= len(it["text"]) for s in it["spans"]), it["id"]
    return items


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 0.0
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def judge(it: dict) -> tuple[bool, set[str]]:
    """(맞음 — 양성은 맞힘·음성은 오탐 없음, 가린 종류)."""
    found = [f for f in find_all(it["text"]) if f.mask]
    kinds = {f.kind for f in found}
    if it["set"] == "neg":
        return not kinds, kinds
    return all(any(f.kind == s["kind"] and f.start <= s["start"] and f.end >= s["end"] for f in found) for s in it["spans"]), kinds


def score(items: list[dict]) -> dict:
    hit, total, fp = Counter(), Counter(), Counter()
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    neg_groups: dict[str, Counter] = defaultdict(Counter)
    missed, false_pos, neg = [], [], 0
    for it in items:
        ok, kinds = judge(it)
        if it["set"] == "pos":
            kind = it["spans"][0]["kind"]
            total[kind] += 1
            hit[kind] += ok
            groups[it["group"]][0] += ok
            groups[it["group"]][1] += 1
            if not ok:
                missed.append(it["id"])
            continue
        neg += 1
        neg_groups[it["group"]]["n"] += 1
        neg_groups[it["group"]]["any"] += not ok
        for k in kinds:
            fp[k] += 1
            neg_groups[it["group"]][k] += 1
        if not ok:
            false_pos.append(it["id"])
    return {"hit": dict(hit), "total": dict(total), "fp": dict(fp), "fp_any": len(false_pos), "neg": neg,
            "groups": dict(sorted(groups.items())), "neg_groups": dict(neg_groups), "missed": missed, "false_pos": false_pos}


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "—"


def ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{100 * lo:.1f}~{100 * hi:.1f}%"


def table(res: dict, title: str) -> str:
    n = res["neg"]
    out = [f"### {title}", "", f"| 종류 | 재현율 | 95% 구간 | 오탐(음성 {n:,}건) | 95% 구간 |", "|---|---|---|---|---|"]
    for k in KINDS:
        h, t, f = res["hit"].get(k, 0), res["total"].get(k, 0), res["fp"].get(k, 0)
        out.append(f"| {k} | {h}/{t} ({pct(h, t)}) | {ci(h, t)} | {f} ({pct(f, n)}) | {ci(f, n)} |")
    h, t, f = sum(res["hit"].values()), sum(res["total"].values()), res["fp_any"]
    out.append(f"| 전체 | {h}/{t} ({pct(h, t)}) | {ci(h, t)} | {f} ({pct(f, n)}) | {ci(f, n)} |")
    out += ["", "| 양성 묶음 | 맞힘 |", "|---|---|"] + [f"| {g} | {h}/{t} |" for g, (h, t) in res["groups"].items()]
    out += ["", "| 음성 묶음 | 오탐 | 잡힌 종류 |", "|---|---|---|"]
    for g, c in res["neg_groups"].items():
        kinds = ", ".join(f"{k} {c[k]}" for k in KINDS if c[k]) or "—"
        out.append(f"| {g} | {c['any']}/{c['n']} | {kinds} |")
    return "\n".join(out)


def hard_table(items: list[dict]) -> str:
    out = ["### hard.jsonl (사례별, 게이트 밖)", "", "| id | 정답 | 결과 | 메모 |", "|---|---|---|---|"]
    for it in items:
        ok, kinds = judge(it)
        want = it["spans"][0]["kind"] if it["spans"] else "없음"
        got = ("맞힘" if ok else "놓침") if it["spans"] else ("통과" if ok else "오탐")
        out.append(f"| {it['id']} | {want} | {got}{' (' + ', '.join(sorted(kinds)) + ')' if kinds else ''} | {it['note']} |")
    return "\n".join(out)


if __name__ == "__main__":
    paths = [Path(a) for a in sys.argv[1:]] or [HERE / "corpus.jsonl"]
    for p in paths:
        print(table(score(load(p)), p.name), end="\n\n")
    if not sys.argv[1:]:
        print(hard_table(load(HERE / "hard.jsonl")))
