#!/usr/bin/env python3
"""정상 질문셋 실행기 — FPR·지연 측정용 원본 데이터를 남긴다.

`validate_benign.py`와 목적이 다르다. 그쪽은 "질문셋이 안정적인가"를 검증했고,
이건 "방어 ON/OFF에서 응답이 어떻게 달라지는가"를 나중에 비교하기 위해
**응답 원문을 전부 보존한다.** 목적이 다르므로 기존 스크립트를 고치지 않고 새로 만든다.

핵심: 응답 헤더의 X-Gateway-Request-Id를 함께 기록한다.
      이 값으로 감사 로그(logs/gateway.jsonl)의 해당 줄과 정확히 대조할 수 있다.
      "이 응답이 마스킹된 요청의 결과인가"를 추측이 아니라 로그로 판정하기 위해서다.

사용:
  BASE_URL=http://localhost:8080 RUNS=5 \
    python3 eval/fpr_run.py eval/benign/all100.jsonl results/fpr_gw_none.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("BASE_URL") or os.environ["TARGET_URL"]
SLUG = os.environ["WORKSPACE_SLUG"]
HDR = {"Authorization": f"Bearer {os.environ['TARGET_API_KEY']}",
       "Content-Type": "application/json"}
RUNS = int(os.environ.get("RUNS", "5"))
SLEEP = float(os.environ.get("SLEEP", "1.5"))
TIMEOUT = float(os.environ.get("TIMEOUT", "300"))


def norm(s: str) -> str:
    return s.replace(" ", "").replace(" ", "")


def ask(msg: str) -> dict:
    """1회 호출. 실패해도 예외를 올리지 않고 결과에 남긴다(측정이 중단되면 안 된다)."""
    sid = "fpr-" + uuid.uuid4().hex[:16]   # 고유 세션 → 대화 이력 오염 차단 (D-013)
    req = urllib.request.Request(
        f"{BASE}/api/v1/workspace/{SLUG}/chat",
        data=json.dumps({"message": msg, "mode": "query", "sessionId": sid},
                        ensure_ascii=False).encode("utf-8"),
        headers=HDR)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            elapsed = (time.perf_counter() - t0) * 1000
            body = json.load(r)
            return {
                "session_id": sid,
                "request_id": r.headers.get("X-Gateway-Request-Id"),
                "status": r.status,
                "elapsed_ms": round(elapsed, 2),
                "text": body.get("textResponse", ""),
                "gateway_blocked": bool(body.get("gateway_blocked")),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {"session_id": sid, "request_id": e.headers.get("X-Gateway-Request-Id"),
                "status": e.code, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "text": "", "gateway_blocked": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"session_id": sid, "request_id": None, "status": None,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "text": "", "gateway_blocked": False, "error": type(e).__name__}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("사용: python3 eval/fpr_run.py <질문셋.jsonl> <출력.jsonl>")
        return 1
    src, dst = argv[0], argv[1]
    items = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    total = len(items) * RUNS
    print(f"대상 {BASE}\n{len(items)}문항 x {RUNS}회 = {total}회 호출\n출력 {dst}\n")

    done = errors = 0
    t_start = time.perf_counter()
    with open(dst, "w", encoding="utf-8") as out:
        for it in items:
            facts = it.get("facts", {})
            for run in range(RUNS):
                r = ask(it["q"])
                done += 1
                if r["error"]:
                    errors += 1
                n = norm(r["text"])
                hit = [k for k, vs in facts.items() if any(norm(v) in n for v in vs)]
                rec = {
                    "id": it["id"], "cat": it["cat"], "run": run,
                    "pii_labels": it.get("pii", []),
                    "facts_expected": list(facts),
                    "facts_hit": hit,
                    "all_facts_hit": bool(facts) and len(hit) == len(facts),
                    **r,
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()   # 중간에 죽어도 여기까지는 남는다
                time.sleep(SLEEP)
            el = time.perf_counter() - t_start
            eta = el / done * (total - done)
            print(f"[{done:4d}/{total}] {it['id']:8s} 오류 {errors}  "
                  f"경과 {el/60:.1f}분  남은시간 약 {eta/60:.0f}분")

    print(f"\n완료. 총 {done}회, 오류 {errors}회, {(time.perf_counter()-t_start)/60:.1f}분")
    if errors:
        print("⚠ 오류가 있다. 원인을 확인하기 전에는 이 결과로 FPR을 계산하지 말 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
