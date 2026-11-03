"""지연 측정(D-125 §2, 사전 등록) — 사이드카를 띄워 HTTP로 한 건씩 보내고 토큰 길이별 p50·p95를 잰다. 게이트웨이가 더하게 될 지연은 이 왕복이다.
인젝션 분류기(models.json의 `task: "injection"`, D-127)면 `tasks: ["injection"]`으로 같은 버킷을 잰다 — 사이드카의 점수 캐시에 걸리지 않게 회차마다 다른 글이다.

  python -m detect.bench --dir models                 # 버킷 32·64·128·256·510 토큰(510 = [CLS]·[SEP]를 더해 창 하나 512), 버킷마다 예열 10 + 측정 100
  python -m detect.bench --dir models --github        # GitHub Actions: 작업 요약 표 + ::notice 주석(로그 없이 API로 읽힌다)

입력은 한국어 업무 문장(eval/ner/synth.jsonl + eval/injection/benign_ko.jsonl)을 이어 붙인 열에서 정확히 N토큰씩 잘라 만든 20개를 돌려 쓴다.
동시성 1(요청 하나씩), 같은 연결(keep-alive), ONNX 스레드는 --threads(기본 4 = CI 러너의 vCPU). 게이트: 모든 버킷의 HTTP p95 ≤ 40ms.
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from detect.app import create_app  # noqa: E402
from detect.classify import Classifier  # noqa: E402
from detect.fetch import MODELS  # noqa: E402
from detect.ner import NER  # noqa: E402

BUCKETS = (32, 64, 128, 256, 510)
GATE_MS = 40.0
VARIANTS = 20


def pool_text() -> str:
    texts = [json.loads(x)["text"] for f in ("eval/ner/synth.jsonl", "eval/injection/benign_ko.jsonl")
             for x in (ROOT / f).read_text(encoding="utf-8").splitlines() if x]
    return " ".join(texts)


def cut(ner: NER | Classifier, pool: str, offsets: list[tuple[int, int]], n: int, k: int) -> str:
    """pool의 k번째 시작점부터 정확히 n토큰인 텍스트. 잘린 끝에서 낱말이 다르게 쪼개지면 끝을 한 글자씩 당긴다."""
    base = (k * 97) % (len(offsets) - 2 * n - 64)
    for start in range(base, base + 32):              # SentencePiece는 자른 앞머리의 첫 조각이 달라진다 — 시작점을 옮겨 가며 찾는다
        for end in range(start + n - 2, start + n + 8):
            text = pool[offsets[start][0]:offsets[end - 1][1]]
            while text and ner.tokens(text) > n:
                text = text[:-1]
            if ner.tokens(text) == n:
                return text
    raise RuntimeError(f"{n}토큰 텍스트를 만들지 못했다")


def pct(xs: list[float], q: float) -> float:
    """가장 가까운 순위(nearest-rank) 백분위 — 100개면 95번째 값."""
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def serve(model: NER | Classifier) -> tuple[uvicorn.Server, int]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(clf=model) if isinstance(model, Classifier) else create_app(model)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server, port


def run(ner: NER | Classifier, runs: int, warmup: int) -> list[dict]:
    pool = pool_text()
    offsets = ner.tok.encode(pool, add_special_tokens=False).offsets
    task = "injection" if isinstance(ner, Classifier) else "pii_ner"
    server, port = serve(ner)
    conn = http.client.HTTPConnection("127.0.0.1", port)
    results = []
    try:
        for n in BUCKETS:
            # 분류기는 텍스트마다 점수를 캐시한다 — 회차마다 다른 글이어야 추론을 잰다
            texts = [cut(ner, pool, offsets, n, k) for k in range(VARIANTS if task == "pii_ner" else warmup + runs)]
            http_ms, server_ms = [], []
            for i in range(warmup + runs):
                body = json.dumps({"texts": [{"id": "b", "role": "user", "text": texts[i % len(texts)]}], "tasks": [task]}).encode()
                t0 = time.perf_counter()
                conn.request("POST", "/v1/detect", body, {"Content-Type": "application/json"})
                resp = conn.getresponse()
                data = resp.read()
                ms = (time.perf_counter() - t0) * 1000
                if resp.status != 200:
                    raise RuntimeError(f"사이드카 {resp.status}")
                if i >= warmup:
                    http_ms.append(ms)
                    server_ms.append(json.loads(data)["ms"])
            results.append({"tokens": n, "runs": runs, "p50": statistics.median(http_ms), "p95": pct(http_ms, 0.95), "max": max(http_ms),
                            "server_p95": pct(server_ms, 0.95),
                            # 40ms 게이트는 NER의 것이다(D-125) — 분류기의 지연은 게이트가 아니라 비용으로 적는다(D-127 G4)
                            "pass": pct(http_ms, 0.95) <= GATE_MS if task == "pii_ner" else None})
    finally:
        conn.close()
        server.should_exit = True
    return results


def cpu_model() -> str:
    """지연 숫자의 조건 — 러너마다 CPU가 다르다(GitHub 러너는 AMD EPYC·Intel Xeon이 섞인다)."""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    try:
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def table(results: list[dict], title: str) -> str:
    lines = [f"### {title}", "", "| 토큰 | p50 ms | **p95 ms** | 최대 ms | 사이드카 안 p95 ms | ≤ 40ms |", "|---:|---:|---:|---:|---:|:-:|"]
    for r in results:
        gate = "—" if r["pass"] is None else "통과" if r["pass"] else "미달"
        lines.append(f"| {r['tokens']} | {r['p50']:.1f} | **{r['p95']:.1f}** | {r['max']:.1f} | {r['server_p95']:.1f} | {gate} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="사이드카 지연 측정(D-125)")
    ap.add_argument("--model", default="veil-ko-lite-int8")
    ap.add_argument("--dir", type=Path, default=Path("models"))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--github", action="store_true")
    a = ap.parse_args()
    model = (Classifier if MODELS[a.model].get("task") == "injection" else NER)(a.model, a.dir, threads=a.threads)
    results = run(model, a.runs, a.warmup)
    host = f"{cpu_model()} · {os.uname().machine} · {os.cpu_count()} CPU · threads {a.threads}"
    text = table(results, f"{a.model} 지연 — {host}")
    verdict = "게이트 없음(비용)" if results[0]["pass"] is None else "통과" if all(r["pass"] for r in results) else "미달"
    if a.github:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + f"\n게이트(모든 버킷 p95 ≤ {GATE_MS:.0f}ms): **{verdict}**\n")
        print(f"::notice title=detect-bench {a.model} ({host})::"
              + " ".join(f"{r['tokens']}tok p50={r['p50']:.1f} p95={r['p95']:.1f}" for r in results) + f" gate={verdict}")
    print(json.dumps({"model": a.model, "host": host, "results": results, "verdict": verdict}, ensure_ascii=False)
          if a.json else text + f"\n게이트: {verdict}")


if __name__ == "__main__":
    main()
