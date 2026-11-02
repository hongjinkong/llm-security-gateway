"""NER F1 측정(D-125) — 모델을 평가셋에 돌려 `eval/ner/score.py`의 표를 낸다.

  python -m detect.evaluate --dir models                          # 합성 200문장(synth.jsonl)과 KDPII test(kdpii_test.jsonl)
  python -m detect.evaluate --dir models --gold a.jsonl --json    # 다른 정답 파일, 기계용 출력
  python -m detect.evaluate --dir models --errors                 # 틀린 문장의 정답·예측 구간(합성 셋에만 쓴다 — 원문이 찍힌다)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.ner import score  # noqa: E402
from detect.ner import NER  # noqa: E402


def predictions(ner: NER, rows: list[dict], kinds: dict[str, str] | None = None) -> list[dict]:
    """제품 종류(person·address·org)로 옮겨지는 구간만 남긴다 — 정형 식별자(전화·이메일…)는 정규식의 몫이라 NER 게이트에 넣지 않는다.
    kinds를 주면 그 대응으로 옮긴다(KDPII의 넓은 규약, D-125 §2-4)."""
    out = []
    for r in rows:
        spans = [(kinds.get(s["label"]) if kinds is not None else s["kind"], s) for s in ner.predict(r["text"])]
        out.append({"id": r["id"], "spans": [{"kind": k, "start": s["start"], "end": s["end"]} for k, s in spans if k]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="NER F1 측정(D-125)")
    ap.add_argument("--model", default="veil-ko-lite-int8")
    ap.add_argument("--dir", type=Path, default=Path("models"))
    ap.add_argument("--gold", type=Path, action="append")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--github", action="store_true", help="::notice 주석으로 F1을 남긴다(GitHub Actions)")
    a = ap.parse_args()
    ner = NER(a.model, a.dir, threads=a.threads)
    out = {}
    for gold in a.gold or [ROOT / "eval" / "ner" / "synth.jsonl", ROOT / "eval" / "ner" / "kdpii_test.jsonl"]:
        rows = score.load(gold)
        kdpii = gold.name.startswith("kdpii")
        ner.merge = frozenset() if kdpii else frozenset(ner.spec.get("merge", ()))     # KDPII는 주소를 구성 요소마다 단다 — 잇지 않는다
        preds = predictions(ner, rows, ner.spec.get("kinds_kdpii") if kdpii else None)
        result = out[gold.name] = score.score(rows, preds)
        if not a.json:
            print(score.table(result, f"{a.model} — {gold.name}"))
        if a.github:
            print(f"::notice title=detect-f1 {a.model} {gold.name}::exact micro F1={result['all']['exact']['f1']:.3f} "      # stderr — 작업 요약(tee)에 섞이지 않게
                  + " ".join(f"{k}={result[k]['exact']['f1']:.3f}" for k in score.KINDS), file=sys.stderr)
        if a.errors:
            for r, p in zip(rows, preds):
                g = sorted((s["kind"], s["start"], s["end"]) for s in r["spans"])
                q = sorted((s["kind"], s["start"], s["end"]) for s in p["spans"])
                if g != q:
                    t = r["text"]
                    print(r["id"], "|", t, "\n   정답", [(k, t[s:e]) for k, s, e in g], "\n   예측", [(k, t[s:e]) for k, s, e in q])
    if a.json:
        print(json.dumps({"name": a.model, **ner.info(), "sets": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
