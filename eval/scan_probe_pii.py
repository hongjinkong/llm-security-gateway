#!/usr/bin/env python3
"""공격 프롬프트에 PII 탐지기가 발동하는지 확인한다.

왜 이걸 재는가:
  "PII 레이어는 ASR을 바꾸지 않을 것"이라는 예상을 사실로 바꾸기 위해서다.
  garak이 실제로 보낸 프롬프트에 PII가 한 건도 없다면, pii_mask 구성에서
  게이트웨이가 타겟에 전달하는 바이트가 검사기 0개 구성과 **완전히 동일**해진다.
  같은 입력에는 같은 분포의 출력이 나오므로 ASR 재측정은 논리적으로 불필요해진다.
  반대로 한 건이라도 걸리면 재측정을 건너뛸 근거가 사라진다.

사용:
  python eval/scan_probe_pii.py results/*.report.jsonl
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gateway.detectors.pii import find_all  # noqa: E402


def prompt_text(attempt: dict) -> str:
    """garak 0.15의 prompt는 {"turns":[{"role","content":{"text"}}]} 구조다."""
    p = attempt.get("prompt")
    if isinstance(p, str):
        return p
    out: list[str] = []

    def walk(o) -> None:
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("lang", "data_type", "data_path", "data_checksum", "role"):
                    continue
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(p)
    return "\n".join(out)


def scan(path: pathlib.Path) -> tuple[int, collections.Counter, list]:
    seen: set[str] = set()
    hits: collections.Counter = collections.Counter()
    examples: list = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("entry_type") != "attempt":
                continue
            t = prompt_text(d)
            if not t or t in seen:
                continue
            seen.add(t)
            for fnd in find_all(t):
                hits[fnd.kind] += 1
                if len(examples) < 8:
                    examples.append((d.get("probe_classname"), fnd.kind, fnd.confidence,
                                     t[max(0, fnd.start - 40):fnd.end + 25].replace("\n", " ")))
    return len(seen), hits, examples


def main(argv: list[str]) -> int:
    if not argv:
        print("사용: python eval/scan_probe_pii.py <report.jsonl> [...]")
        return 1
    total_prompts = 0
    total_hits: collections.Counter = collections.Counter()
    for arg in argv:
        path = pathlib.Path(arg)
        if not path.exists():
            print(f"없음: {path}")
            continue
        n, hits, examples = scan(path)
        total_prompts += n
        total_hits.update(hits)
        print(f"\n{path.name}")
        print(f"  고유 프롬프트 : {n}개")
        print(f"  PII 탐지      : {dict(hits) if hits else '0건'}")
        for probe, kind, conf, snippet in examples:
            print(f"    └ {probe} / {kind}({conf}) … {snippet[:90]}")

    print("\n" + "=" * 60)
    print(f"전체 고유 프롬프트 {total_prompts}개")
    if total_hits:
        print(f"PII 탐지 {sum(total_hits.values())}건 {dict(total_hits)}")
        print("→ 공격 프롬프트가 마스킹된다. pii_mask 구성의 ASR 재측정을 생략할 근거가 없다.")
        return 2
    print("PII 탐지 0건")
    print("→ pii_mask 구성에서 타겟이 받는 바이트가 검사기 0개 구성과 동일하다.")
    print("  ASR 재측정은 논리적으로 불필요. 단, 이 결론은 이 리포트에 담긴 프롬프트에 한정된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
