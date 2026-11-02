#!/usr/bin/env python3
"""이름·주소 가림의 지연(D-126 §2-10) — **실제 탐지 사이드카** 앞에서 게이트웨이 경유 왕복을 잰다. 상류는 자기 스텁이라 외부 공급자로는 아무것도 나가지 않는다.

  DETECT_MODEL_DIR=models .venv-detect/bin/python -m uvicorn detect.app:app --port 8081 --no-access-log &     # 사이드카(별도 가상환경, detect/README.md)
  python3 scripts/ner_latency.py --detect http://127.0.0.1:8081 --long long510.jsonl [--runs 100]

장면(값은 모두 합성 — eval/ner/make_synth.py의 사전으로 회차마다 다른 글을 만든다):
  short-off   짧은 새 턴(이름·주소 든 한 문장) — 이름·주소를 켜지 않은 정책(기준선)
  short-on    같은 글 — 이름·주소를 켠 정책(캐시에 없는 새 글이라 사이드카 왕복 하나)
  turn2       둘째 턴(턴 1의 user 메시지 = 캐시, 턴 1의 답은 새 글, 새 질문 한 줄)
  turn3       셋째 턴(이력은 모두 캐시, 새 질문 한 줄만 사이드카로)
  long510     510토큰 새 텍스트(--long 파일의 줄, 회차마다 다른 줄 — detect/bench.py와 같은 길이)
숫자: 클라이언트가 본 왕복 p50·p95(ms), 감사 줄의 gateway_ms·검사기 항목의 ner_ms p50·p95. 원문은 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.ner import make_synth  # noqa: E402
from gateway.detectors.pii import ALL_KINDS  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.settings import Settings  # noqa: E402
from tests.conftest import free_port, start, stop  # noqa: E402
from tests.stub_target import app as stub_app  # noqa: E402

CHAT = "/v1/chat/completions"


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def short_text(r: random.Random) -> str:
    return f"고객 {make_synth.person(r)} 님의 주소는 {make_synth.address(r)}입니다. 배송 일정을 알려 주세요."


def main() -> int:
    ap = argparse.ArgumentParser(description="이름·주소 가림 지연(D-126)")
    ap.add_argument("--detect", required=True, help="실제 탐지 사이드카 주소")
    ap.add_argument("--long", type=Path, help="510토큰 텍스트 JSONL({'text'}) — 없으면 long510 장면을 건너뛴다")
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=5)
    a = ap.parse_args()
    for name in [n for n in os.environ if n.startswith(("GATEWAY_", "TARGET_", "STUB_", "UVICORN_"))]:
        del os.environ[name]
    health = httpx.get(a.detect + "/health", timeout=10).json()
    print("사이드카:", json.dumps(health["tasks"]["pii_ner"], ensure_ascii=False))

    log = Path(tempfile.mkdtemp(prefix="ner-latency-")) / "gateway.jsonl"
    sp = free_port()
    servers = [start(stub_app, sp)]
    base = {"TARGET_URL": f"http://127.0.0.1:{sp}", "GATEWAY_AUTH": "off", "GATEWAY_LOG_PATH": str(log),
            "GATEWAY_SURROGATE_KEY": "ner-latency-surrogate-key-not-a-secret", "GATEWAY_DETECT_TIMEOUT": "60"}
    ports = {}
    for name, extra in (("off", {}), ("on", {"GATEWAY_PII_KINDS": ",".join(ALL_KINDS), "GATEWAY_DETECT_URL": a.detect})):
        ports[name] = free_port()
        servers.append(start(create_app(Settings.from_env({**base, **extra})), ports[name]))
    clients = {name: httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) for name, port in ports.items()}
    rng = random.Random(20261102)
    rows: dict[str, list[tuple[float, str]]] = {}

    def post(name: str, messages: list[dict]) -> tuple[float, str, dict]:
        t0 = time.perf_counter()
        r = clients[name].post(CHAT, json={"model": "stub-model", "messages": messages})
        ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        return ms, r.headers["x-gateway-request-id"], r.json()["choices"][0]["message"]

    def record(scene: str, ms: float, rid: str, warm: bool) -> None:
        if not warm:
            rows.setdefault(scene, []).append((ms, rid))

    try:
        for i in range(a.warmup + a.runs):
            warm = i < a.warmup
            text = short_text(rng)
            user = {"role": "user", "content": text}
            ms, rid, _ = post("off", [user])
            record("short-off", ms, rid, warm)
            ms, rid, answer = post("on", [user])
            record("short-on", ms, rid, warm)
            history = [user, answer, {"role": "user", "content": "배송 전에 문자 한 통 부탁드려요."}]
            ms, rid, answer2 = post("on", history)
            record("turn2", ms, rid, warm)
            ms, rid, _ = post("on", history + [answer2, {"role": "user", "content": "네, 감사합니다."}])
            record("turn3", ms, rid, warm)
        if a.long:
            longs = [json.loads(x)["text"] for x in a.long.read_text(encoding="utf-8").splitlines() if x]
            for i in range(min(len(longs), a.warmup + a.runs)):
                ms, rid, _ = post("on", [{"role": "user", "content": longs[i]}])
                record("long510", ms, rid, i < a.warmup)
    finally:
        for c in clients.values():
            c.close()
        stop(servers)

    lines = {x["request_id"]: x for x in (json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line)}
    print("\n| 장면 | n | 왕복 p50 · p95 (ms) | gateway_ms p50 · p95 | ner_ms p50 · p95 | 가린 이름·주소(합) |")
    print("|---|---|---|---|---|---|")
    for scene, items in rows.items():
        rt = [ms for ms, _ in items]
        gw = [lines[rid]["gateway_ms"] for _, rid in items]
        steps = [next((d for d in lines[rid]["detectors"] if d["detector"] == "pii_mask"), {}) for _, rid in items]
        ner = [d.get("ner_ms", 0.0) for d in steps]
        masked = sum(d.get("pii", {}).get(k, 0) for d in steps for k in ("person", "address"))
        print(f"| {scene} | {len(rt)} | {pct(rt, .5):.1f} · {pct(rt, .95):.1f} | {pct(gw, .5):.1f} · {pct(gw, .95):.1f} | "
              f"{pct(ner, .5):.1f} · {pct(ner, .95):.1f} | {masked} |")
    print(f"\n평균 상류(스텁) 시간 {statistics.mean(lines[rid]['upstream_ms'] for items in rows.values() for _, rid in items):.1f}ms · 감사 로그 {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
