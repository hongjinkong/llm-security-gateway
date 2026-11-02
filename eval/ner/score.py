#!/usr/bin/env python3
"""NER 평가 점수(D-125, PLAN 17단계) — 예측 구간을 정답과 맞춰 종류별·전체 정밀도·재현율·F1을 낸다. 표준 라이브러리만.

  python3 eval/ner/score.py PRED.jsonl                 # 정답은 synth.jsonl
  python3 eval/ner/score.py PRED.jsonl GOLD.jsonl --json

예측 한 줄: {"id", "spans": [{"kind", "start", "end"}]} — 정답과 같은 id. 종류는 person·address·org만 센다(그 밖은 버린다).
  exact    시작·끝·종류가 모두 같아야 맞힘(CoNLL 방식). **게이트는 세 종류를 합친 exact micro F1이다**(D-125 §2).
  overlap  같은 종류로 한 글자라도 겹치면 맞힘 — 정답 하나에 예측 하나씩만 짝짓는다.
  char     정답 글자 가운데 예측 구간(종류 무관)이 덮은 비율 — 가렸다면 상류로 새지 않는다는 뜻의 재현율.
원문은 출력하지 않는다(숫자와 id만).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from eval.pii.score import wilson  # noqa: E402

KINDS = ("person", "address", "org")
ALL = "all"


def load(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    for row in rows:
        n = len(row["text"]) if "text" in row else None
        for s in row["spans"]:
            assert 0 <= s["start"] < s["end"] and (n is None or s["end"] <= n), row["id"]
    return rows


def _spans(row: dict) -> list[tuple[str, int, int]]:
    return [(s["kind"], s["start"], s["end"]) for s in row["spans"] if s["kind"] in KINDS]


def _prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    return {"tp": tp, "pred": n_pred, "gold": n_gold, "p": p, "r": r, "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "p_ci": wilson(tp, n_pred), "r_ci": wilson(tp, n_gold)}


def score(gold_rows: list[dict], pred_rows: list[dict]) -> dict:
    preds = {row["id"]: _spans(row) for row in pred_rows}
    missing = [row["id"] for row in gold_rows if row["id"] not in preds]
    if missing:
        raise ValueError(f"예측이 없는 id {len(missing)}개: {missing[:3]}")
    exact: Counter[str] = Counter()
    overlap: Counter[str] = Counter()
    n_gold: Counter[str] = Counter()
    n_pred: Counter[str] = Counter()
    chars: Counter[str] = Counter()
    covered: Counter[str] = Counter()
    for row in gold_rows:
        gold, pred = _spans(row), preds[row["id"]]
        n_gold.update(k for k, _, _ in gold)
        n_pred.update(k for k, _, _ in pred)
        exact.update(k for k, _, _ in set(gold) & set(pred))
        used: set[int] = set()
        for k, s, e in gold:
            j = next((j for j, (pk, ps, pe) in enumerate(pred) if j not in used and pk == k and ps < e and s < pe), None)
            if j is not None:
                used.add(j)
                overlap[k] += 1
            chars[k] += e - s
            covered[k] += sum(1 for i in range(s, e) if any(ps <= i < pe for _, ps, pe in pred))
    out: dict = {"rows": len(gold_rows)}
    for k in (*KINDS, ALL):
        def total(c: Counter[str]) -> int:
            return sum(c.values()) if k == ALL else c[k]
        out[k] = {"exact": _prf(total(exact), total(n_pred), total(n_gold)),
                  "overlap": _prf(total(overlap), total(n_pred), total(n_gold)),
                  "char_recall": total(covered) / total(chars) if total(chars) else 0.0}
    return out


def table(result: dict, title: str = "") -> str:
    head = [f"### {title}", ""] if title else []
    lines = head + ["| 종류 | 정답 | 예측 | exact P | exact R | **exact F1** | overlap F1 | 글자 재현율 |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k in (*KINDS, ALL):
        e, o = result[k]["exact"], result[k]["overlap"]
        lines.append(f"| {'전체(micro)' if k == ALL else k} | {e['gold']} | {e['pred']} | {e['p']:.3f} | {e['r']:.3f} | **{e['f1']:.3f}** | "
                     f"{o['f1']:.3f} | {result[k]['char_recall']:.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="NER 평가 점수(D-125)")
    ap.add_argument("pred", type=Path)
    ap.add_argument("gold", type=Path, nargs="?", default=HERE / "synth.jsonl")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    result = score(load(a.gold), load(a.pred))
    print(json.dumps(result, ensure_ascii=False) if a.json else table(result, a.gold.name))


if __name__ == "__main__":
    main()
