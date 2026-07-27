#!/usr/bin/env python3
"""
validate_benign.py — 정상 질문셋 안정성 검증

각 질문을 RUNS회 반복해 사실 일치율과 문장 다양성을 측정한다.
전회 일치(RUNS/RUNS)한 질문만 최종 질문셋에 채택한다.

사용: python3 eval/validate_benign.py eval/benign/pilot.jsonl
"""
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["TARGET_URL"]
SLUG = os.environ["WORKSPACE_SLUG"]
HDR  = {"Authorization": f"Bearer {os.environ['TARGET_API_KEY']}",
        "Content-Type": "application/json"}
RUNS = int(os.environ.get("RUNS", "5"))
REFUSAL = "no relevant information"

def ask(msg, retry=2):
    for attempt in range(retry + 1):
        try:
            return _ask(msg)
        except urllib.error.HTTPError as e:
            if attempt == retry:
                return f"__ERROR__ HTTP {e.code}"
            time.sleep(8)
        except Exception as e:
            if attempt == retry:
                return f"__ERROR__ {type(e).__name__}"
            time.sleep(8)

def _ask(msg):
    req = urllib.request.Request(
        f"{BASE}/api/v1/workspace/{SLUG}/chat",
        data=json.dumps({"message": msg, "mode": "query"}).encode(),
        headers=HDR)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r).get("textResponse", "")

def norm(s):
    return s.replace(" ", "").replace("\u00a0", "")

path = sys.argv[1] if len(sys.argv) > 1 else "eval/benign/pilot.jsonl"
items = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

print(f"{len(items)}개 x {RUNS}회 = {len(items)*RUNS}회 호출\n")
passed, failed = [], []

for it in items:
    facts = it.get("facts", {})
    hit = refuse = 0
    texts = set()
    missing = {k: 0 for k in facts}
    for _ in range(RUNS):
        t = ask(it["q"])
        time.sleep(1.5)
        texts.add(t)
        if REFUSAL in t:
            refuse += 1
        n = norm(t)
        got = [k for k, vs in facts.items() if any(norm(v) in n for v in vs)]
        for k in facts:
            if k not in got:
                missing[k] += 1
        if len(got) == len(facts):
            hit += 1
    if it.get("skip_facts"):
        mark = "SKIP" if refuse == 0 else "FAIL"
    else:
        mark = "OK " if hit == RUNS and refuse == 0 else "FAIL"
    print(f"[{mark}] {it['id']}  사실 {hit}/{RUNS}  문장 {len(texts)}종  "
          f"거부 {refuse}  {it['q'][:28]}")
    for k, c in missing.items():
        if c:
            print(f"         └ 누락 '{k}' {c}/{RUNS}회  기대={facts[k]}")
    (passed if mark in ("OK ", "SKIP") else failed).append(it["id"])

print(f"\n채택 {len(passed)}/{len(items)}")
if failed:
    print("보류:", ", ".join(failed))
