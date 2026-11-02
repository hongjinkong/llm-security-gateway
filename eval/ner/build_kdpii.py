#!/usr/bin/env python3
"""NER 공개 평가셋 — KDPII test를 이 저장소의 스키마로 옮긴다(D-125 §2-4). 표준 라이브러리만, 결정적.

  python3 eval/ner/build_kdpii.py                # 고정 리비전에서 받아(SHA-256 확인) kdpii_test.jsonl을 다시 쓴다
  python3 eval/ner/build_kdpii.py --src FILE     # 이미 받은 원본으로

원본: 1T/veil-pii-ko-stress(CC BY 4.0)의 leakage/kdpii_test_dedup.jsonl — KDPII test(CC BY 4.0)에서 train과 완전히 같은 행을 뺀 4,799행, 문자 위치 구간.
바꾼 것: PERSON·ADDRESS·ORGANIZATION 구간만 person·address·org로 남기고 나머지 구간과 필드(lang·source·aug·valid·bad)를 뺐다. 행과 순서는 그대로다. 출처는 SOURCES.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = ("https://huggingface.co/datasets/1T/veil-pii-ko-stress/resolve/1a3106d85d5bfd3851128ce14535a27038f051a4/"
       "leakage/kdpii_test_dedup.jsonl")
SRC_SHA256 = "2567966e4dd3452ec2994090a3b5a085314c056cf4df5ed4b3d57ab31150023d"
KEEP = {"PERSON": "person", "ADDRESS": "address", "ORGANIZATION": "org"}


def convert(raw: bytes) -> str:
    got = hashlib.sha256(raw).hexdigest()
    if got != SRC_SHA256:
        raise SystemExit(f"원본 SHA-256 불일치 {got} != {SRC_SHA256}")
    out = []
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        spans = sorted(({"kind": KEEP[s["label"]], "start": s["start"], "end": s["end"]} for s in row["spans"] if s["label"] in KEEP),
                       key=lambda s: (s["start"], s["end"]))
        out.append(json.dumps({"id": row["id"], "text": row["text"], "spans": spans}, ensure_ascii=False) + "\n")
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="KDPII test → eval/ner/kdpii_test.jsonl(D-125)")
    ap.add_argument("--src", type=Path)
    a = ap.parse_args()
    raw = a.src.read_bytes() if a.src else urllib.request.urlopen(URL, timeout=60).read()
    (HERE / "kdpii_test.jsonl").write_text(convert(raw), encoding="utf-8")


if __name__ == "__main__":
    main()
