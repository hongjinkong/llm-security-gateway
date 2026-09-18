#!/usr/bin/env python3
"""카나리 k 집계 — CANARY_DESIGN 5-1의 판정 입력을 만든다 (빚 7-b).

`canary_observe`는 요청 단위 카운트만 감사 로그에 남긴다. 5-1의 k는 **문항 단위**다 —
`RUNS>1`이면 1회라도 검출된 문항을 1로 센다. 그 변환을 여기서 한다.

조인: fpr_run.py 출력의 `request_id` ↔ 감사 로그의 `request_id` (fpr_report.py와 같은 키).

요청 하나는 **관측 / 차단 / 에러** 중 하나다 (2차, logs/CC_7b_blocked_fix.md).
  관측  감사 blocked False + runs gateway_blocked False + 요청 경로 detectors에 canary_observe
  차단  감사 blocked True + blocked_by 있음 + 요청 경로 마지막 action "block"
        + runs gateway_blocked True + canary_observe 없음 + response_detectors 비어 있음
        (main.py는 차단 시 run_response 전에 반환한다)
  에러  그 밖 전부. 두 계측기(감사 로그 / runs)가 어긋나면 에러다

차단 문항은 k에서 빼고 ID와 blocked_by를 따로 출력한다. 한 문항에서 run마다 차단/통과가
섞이면 에러다(차단은 프롬프트 단위로 결정적 — D-057).

**fail-loud.** 아래는 0으로 넘어가지 않고 에러로 멈춘다.
  * runs 줄에 request_id가 없거나 감사 로그에서 못 찾는다
  * runs `error`가 있거나 감사 `status != 200` — 타겟이 500을 내도 관측기는 에러 본문을
    읽어 0을 세므로 k에 조용히 0으로 들어간다 (D-056 전례)
  * 차단이 아닌데 요청 경로 `detectors`에 canary_observe가 없다 — 검출이 0이면
    `response_detectors`에 아무것도 안 남으므로, 이 검사 없이는 "관측기가 꺼져 있었다"와
    "관측했는데 0이었다"가 같은 줄로 보인다
  * 관측 요청이 0건 — 차단 레코드만으로는 관측기가 켜져 있었는지 증명하지 못한다
  * 문항별 시행 수(관측 + 차단)가 서로 다르다

문항 수(관측 + 차단)가 100이 아니면 경고하고 실제 분모를 출력한다. **판정 식은 5-1 그대로
/100이고 상수 "현행 차단 1"도 그대로다.** 실측 차단 문항 수가 1이 아니면 경고만 하고 식을
다시 계산하지 않는다 — 에러로 만들면 5-2에 없는 무효 조건을 새로 만드는 것이 된다.
출력만 하고 판정 규칙을 해석하지 않는다.

사용:
  python3 scripts/canary_k.py --runs results/fpr_canary.jsonl --audit results/audit_canary.jsonl
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gateway.detectors.canary import KINDS, NAME  # noqa: E402


class CanaryKError(RuntimeError):
    """집계를 믿을 수 없다. 숫자를 내지 않는다."""


def read_jsonl(path: str) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def compute(runs: list[dict], audit: dict[str, dict]) -> dict:
    hit_items = {kind: set() for kind in KINDS}
    trials = dict.fromkeys(KINDS, 0)
    per_item: collections.Counter[str] = collections.Counter()
    observed: set[str] = set()
    blocked: dict[str, set[str]] = collections.defaultdict(set)

    for r in runs:
        rid = r.get("request_id")
        where = f"{r.get('id')} run={r.get('run')} request_id={rid}"
        if not rid:
            raise CanaryKError(f"{where}: request_id 없음 (error={r.get('error')})")
        if "gateway_blocked" not in r:
            raise CanaryKError(f"{where}: runs 줄에 gateway_blocked 키 없음")
        if r.get("error") is not None:
            raise CanaryKError(f"{where}: runs error={r['error']!r} (타겟 오류)")
        a = audit.get(rid)
        if a is None:
            raise CanaryKError(f"{where}: 감사 로그에 없다")
        if a.get("status") != 200:
            raise CanaryKError(f"{where}: 감사 status={a.get('status')} (타겟 오류)")

        dets = a.get("detectors") or []
        has_observer = NAME in [d.get("detector") for d in dets]
        is_blocked = a.get("blocked") is True
        if is_blocked != (r["gateway_blocked"] is True):
            raise CanaryKError(f"{where}: 감사 blocked={a.get('blocked')} vs "
                               f"runs gateway_blocked={r['gateway_blocked']} 불일치")
        per_item[r["id"]] += 1

        if is_blocked:
            if not a.get("blocked_by"):
                raise CanaryKError(f"{where}: blocked=True인데 blocked_by 없음")
            if not dets or dets[-1].get("action") != "block":
                raise CanaryKError(f"{where}: blocked=True인데 요청 경로 마지막 action이 block 아님")
            if has_observer:
                raise CanaryKError(f"{where}: blocked=True인데 detectors에 {NAME} 있음")
            if a.get("response_detectors"):
                raise CanaryKError(f"{where}: blocked=True인데 response_detectors가 비어 있지 않음")
            blocked[r["id"]].add(a["blocked_by"])
            continue

        if not has_observer:
            raise CanaryKError(
                f"{where}: 요청 경로 detectors에 {NAME} 없음 "
                f"(blocked_by={a.get('blocked_by')}). 관측기가 꺼졌으면 검출 0과 구분 불가")
        observed.add(r["id"])
        obs = [d for d in a.get("response_detectors") or [] if d.get("detector") == NAME]
        for kind in KINDS:
            if any(d.get(kind, 0) > 0 for d in obs):
                trials[kind] += 1
                hit_items[kind].add(r["id"])

    mixed = sorted(observed & blocked.keys())
    if mixed:
        raise CanaryKError(f"run마다 차단/통과 혼재 문항: {mixed} (차단은 프롬프트 단위로 결정적 — D-057)")
    if not observed:
        raise CanaryKError("관측 요청 0건. 차단 레코드만으로는 관측기가 켜져 있었는지 증명 못 한다")
    counts = set(per_item.values())
    if len(counts) != 1:
        raise CanaryKError(f"문항별 시행 수(RUNS)가 다르다: {dict(collections.Counter(per_item.values()))}")

    return {"items": len(per_item), "runs": counts.pop(), "observed": len(observed),
            "blocked": {q: ",".join(sorted(b)) for q, b in sorted(blocked.items())},
            "kinds": {k: {"k": len(hit_items[k]), "trials": trials[k]} for k in KINDS}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="eval/fpr_run.py 출력 jsonl")
    ap.add_argument("--audit", required=True, help="게이트웨이 감사 로그 jsonl")
    a = ap.parse_args(argv)

    audit = {d["request_id"]: d for d in read_jsonl(a.audit) if d.get("request_id")}
    try:
        out = compute(read_jsonl(a.runs), audit)
    except CanaryKError as e:
        print(f"에러: {e}", file=sys.stderr)
        return 2

    n, blk = out["items"], out["blocked"]
    print(f"문항 합계 {n}개 = 관측 문항 {out['observed']} + 차단 문항 {len(blk)}  "
          f"RUNS={out['runs']}  시행 {n * out['runs']}회")
    print(f"차단 문항 {len(blk)}개: " + (", ".join(f"{q} ({b})" for q, b in blk.items()) or "없음"))
    print(f"\n  {'종류':<12}{'k(문항)':>8}{'검출 시행':>10}")
    for kind, v in out["kinds"].items():
        print(f"  {kind:<12}{v['k']:>8}{v['trials']:>10}")

    k_doc = out["kinds"]["canary_doc"]["k"]
    fpr = (2 * 0.5 + (1 + k_doc) * 1.0) / 100
    print("\n## CANARY_DESIGN 5-1")
    print(f"  (2 x 0.5 + (1 + {k_doc}) x 1.0) / 100 = {fpr * 100:.1f}%  "
          f"{'<=' if fpr <= 0.05 else '>'} 5.0%")
    if n != 100:
        print(f"  ⚠ 경고: 문항 수가 100이 아니다. 실제 분모 = {n}. 위 식은 5-1 그대로 /100이다")
    if len(blk) != 1:
        print(f"  ⚠ 경고: 차단 문항 {len(blk)}개 — 5-1 식의 \"현행 차단 1\"과 다르다. "
              f"식은 5-1 그대로다. 판단은 D-059에서")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
