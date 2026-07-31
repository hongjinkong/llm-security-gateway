# scripts/asr_summary.py
# garak report.jsonl -> (probe, detector)별 ASR + 95% Wilson 신뢰구간
import sys, json, math
from collections import defaultdict

def wilson(k, n, z=1.96):          # k=공격 성공 수, n=전체
    if n == 0: return (0.0, 0.0)
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = (z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / d
    return (max(0.0, c-h), min(1.0, c+h))

def clean(s):
    return s.replace("probes.", "").replace("detector.", "")

agg = defaultdict(lambda: [0, 0])  # (probe, detector) -> [fails, total_evaluated]
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try: r = json.loads(line)
        except json.JSONDecodeError: continue
        if r.get("entry_type") != "eval": continue
        key = (clean(r.get("probe","?")), clean(r.get("detector","?")))
        agg[key][0] += int(r.get("fails", 0))            # 뚫린 횟수 = 공격 성공
        agg[key][1] += int(r.get("total_evaluated", 0))  # 전체 채점 횟수

print("### probe × detector 별")
print("| probe | detector | ASR | 95% CI | n |")
print("|---|---|---|---|---|")
det = defaultdict(lambda: [0, 0])
for (probe, detector), (fails, total) in sorted(agg.items()):
    lo, hi = wilson(fails, total)
    det[detector][0] += fails; det[detector][1] += total
    asr = fails/total*100 if total else 0
    print(f"| {probe} | {detector} | {asr:.1f}% | {lo*100:.1f}–{hi*100:.1f}% | {total} |")

print("\n### detector 별 통합 (판정기끼리는 합치되, 서로 다른 판정기는 절대 안 합침)")
print("| detector | ASR | 95% CI | n |")
print("|---|---|---|---|")
for detector, (fails, total) in sorted(det.items()):
    lo, hi = wilson(fails, total)
    asr = fails/total*100 if total else 0
    print(f"| {detector} | {asr:.1f}% | {lo*100:.1f}–{hi*100:.1f}% | {total} |")
