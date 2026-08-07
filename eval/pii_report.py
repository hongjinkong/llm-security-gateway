#!/usr/bin/env python3
"""PII 탐지기를 정상 질문셋(EVAL 3.1, 100문항)에 대고 재는 스크립트.

두 숫자를 함께 낸다. 하나만 보면 속는다.
  재현율  SCOPE 4.2 범위의 PII를 가진 문항 중 몇 개를 잡았나 (놓치면 유출)
  오탐    PII가 없는 문항에서 몇 번 잘못 잡았나 (많으면 EVAL 3절 FPR이 무너진다)

실행: python eval/pii_report.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gateway.detectors.pii import find_all  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[1] / "eval" / "benign" / "all100.jsonl"

# 질문셋의 한글 라벨 → 탐지기 종류. SCOPE 4.2에 없는 것은 None(범위 밖).
LABEL = {"주민등록번호": "rrn", "카드번호": "card", "전화번호": "phone", "이메일": "email",
         "계좌번호": None, "이름": None, "사번": None}


def main() -> int:
    rows = [json.loads(x) for x in DATA.read_text(encoding="utf-8").splitlines() if x.strip()]

    hit = miss = 0
    misses: list[str] = []
    fp_rows: list[tuple[str, str, list[str]]] = []
    out_of_scope: set[str] = set()

    for r in rows:
        found = {f.kind for f in find_all(r["q"])}
        expected = set()
        for label in r.get("pii", []):
            kind = LABEL.get(label)
            if kind:
                expected.add(kind)
            else:
                out_of_scope.add(label)

        for kind in expected:
            if kind in found:
                hit += 1
            else:
                miss += 1
                misses.append(f"{r['id']} {kind}")

        extra = found - expected
        if extra:
            fp_rows.append((r["id"], r["cat"], sorted(extra)))

    total = hit + miss
    print(f"문항 수: {len(rows)}\n")
    print("## 재현율 (SCOPE 4.2 범위 PII)")
    print(f"  탐지 {hit} / 전체 {total}  =  {hit / total * 100:.1f}%" if total else "  대상 없음")
    if misses:
        print(f"  놓침: {', '.join(misses)}")

    print("\n## 오탐 (기대하지 않은 탐지)")
    if not fp_rows:
        print("  없음")
    for rid, cat, extra in fp_rows:
        print(f"  {rid} [{cat}] → {extra}")

    print("\n## 범위 밖 PII 라벨 (미탐지가 정상, README 한계로 명시)")
    print(f"  {', '.join(sorted(out_of_scope)) or '없음'}")

    print("\n## 신뢰도 등급 분포")
    conf: dict[str, int] = {}
    for r in rows:
        for f in find_all(r["q"]):
            conf[f"{f.kind}/{f.confidence}"] = conf.get(f"{f.kind}/{f.confidence}", 0) + 1
    for k in sorted(conf):
        print(f"  {k}: {conf[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
