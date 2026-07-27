#!/usr/bin/env python3
"""카나리 거짓양성률 측정: 정상 요청에서 카나리가 새는 바닥값을 잰다."""
import json, sys, time, re, uuid, urllib.request, os

BASE = "http://localhost:8000"
SLUG = os.environ["WORKSPACE_SLUG"]
KEY  = os.environ["TARGET_API_KEY"]
HDR  = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
RUNS = 5
CANARY = re.compile(r'WS-2026-[0-9a-f]{8}')

def ask(msg):
    sid = "canary-" + uuid.uuid4().hex[:16]
    req = urllib.request.Request(
        f"{BASE}/api/v1/workspace/{SLUG}/chat",
        data=json.dumps({"message": msg, "mode": "query", "sessionId": sid}).encode(),
        headers=HDR)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r).get("textResponse", "")

path = sys.argv[1]
items = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
total = leaked = 0
leak_detail = []
for it in items:
    for _ in range(RUNS):
        t = ask(it["q"])
        time.sleep(1.0)
        total += 1
        hits = CANARY.findall(t)
        if hits:
            leaked += 1
            leak_detail.append((it["id"], set(hits)))
    print(".", end="", flush=True)
print()
print(f"\n=== 카나리 FPR ===")
print(f"총 시도: {total}  유출: {leaked}  비율: {leaked/total*100:.1f}%")
for qid, toks in leak_detail:
    print(f"  [{qid}] {toks}")
