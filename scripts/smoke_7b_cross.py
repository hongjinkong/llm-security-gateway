"""7-b 스모크 교차검증 — canary_k.py(감사 로그 기반)와 독립 집계(클라이언트 응답 기반)를 대조한다.

D-058-1 교훈: 두 계측기가 같은 것을 세는지는 문서가 아니라 산출물로 확인한다.

  A  canary_k.compute()  : 감사 로그의 canary_observe meta (응답 본문 전체 기준)
  B  독립 집계           : fpr_run.py가 저장한 textResponse(`text`)에서 직접 문자열 검색

stub은 요청 message를 textResponse와 echo.body 두 곳에 돌려준다.
그래서 요청당 검출 횟수는 A가 B의 2배로 나오는 것이 정상이다(관측 범위 차이, D-058-1).
**문항 단위 k와 검출 시행 수는 둘이 같아야 한다.** 이것이 합격 조건이다.
카나리 값은 찍지 않는다.

사용 (저장소 루트에서, .env 로드 후):
  python3 scripts/smoke_7b_cross.py
입력은 logs/smoke_7b_runs.jsonl · logs/smoke_7b_audit.jsonl (D-058-2 4절 절차).
"""
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import canary_k  # noqa: E402

RUNS_PATH, AUDIT_PATH = "logs/smoke_7b_runs.jsonl", "logs/smoke_7b_audit.jsonl"
TOK = {"canary_a": os.environ["CANARY_A_TOKEN"],
       "canary_b": os.environ["CANARY_B_TOKEN"],
       "canary_doc": os.environ["DOC_CANARY_TOKEN"]}

runs = canary_k.read_jsonl(RUNS_PATH)
audit = {d["request_id"]: d for d in canary_k.read_jsonl(AUDIT_PATH) if d.get("request_id")}
a = canary_k.compute(runs, audit)

b_items = {k: set() for k in TOK}
b_trials = dict.fromkeys(TOK, 0)
per_req_client = collections.defaultdict(dict)
for r in runs:
    if r.get("gateway_blocked"):
        continue
    for k, t in TOK.items():
        n = (r.get("text") or "").count(t)
        per_req_client[r["request_id"]][k] = n
        if n:
            b_trials[k] += 1
            b_items[k].add(r["id"])

print(f"{'종류':<12}{'A k':>6}{'B k':>6}{'A 시행':>8}{'B 시행':>8}")
bad = 0
for k in TOK:
    ak, at = a["kinds"][k]["k"], a["kinds"][k]["trials"]
    bk, bt = len(b_items[k]), b_trials[k]
    ok = ak == bk and at == bt
    bad += not ok
    print(f"{k:<12}{ak:>6}{bk:>6}{at:>8}{bt:>8}  {'✅' if ok else '❌'}")

print("\n요청별 횟수 (A=감사 meta / B=textResponse)")
for r in runs:
    if r.get("gateway_blocked"):
        print(f"  {r['id']:<10} run={r['run']}  차단 (blocked_by={audit[r['request_id']].get('blocked_by')})")
        continue
    obs = [d for d in audit[r["request_id"]].get("response_detectors") or [] if d.get("detector") == canary_k.NAME]
    am = {k: sum(d.get(k, 0) for d in obs) for k in TOK}
    bm = per_req_client[r["request_id"]]
    cells = "  ".join(f"{k[7:]}={am[k]}/{bm[k]}" for k in TOK)
    print(f"  {r['id']:<10} run={r['run']}  {cells}")

tr = collections.Counter(bool(audit[r["request_id"]].get("transformed")) for r in runs)
print(f"\n감사 transformed: {dict(tr)}  (P-111만 true 기대 — pii_mask 요청 경로)")
print("\n문항 단위 대조: " + ("일치" if not bad else f"{bad}종 불일치 — 원인 확인 전 진행 금지"))
sys.exit(1 if bad else 0)
