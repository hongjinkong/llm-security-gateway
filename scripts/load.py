#!/usr/bin/env python3
"""부하·안정성 측정(D-122) — 지연을 주입한 스텁 앞의 게이트웨이에 스트리밍·비스트리밍 요청을 섞어 동시에 보낸다.

  python3 scripts/load.py                                                  # 60초, 스트림 50 + 비스트리밍 50, 기준선(스텁 직접) 포함
  python3 scripts/load.py --duration 1800 --sample 30 --no-baseline --out soak.json   # 30분 soak

게이트웨이는 이미지와 같은 서버 설정(워커 1, asyncio·h11, 접근 로그 끔)으로 띄운다 — 개발 venv의 uvloop·httptools를 쓰면 이미지보다 빠르게 잰다.
요청마다 다른 합성 전화번호를 넣고, 응답에서 원래 번호(복원)와 다른 요청의 번호(교차 누출)를 센다. 세 API를 돌아가며 쓴다.
표본마다 게이트웨이 프로세스의 RSS·열린 파일 수와 `gateway_vault_sessions`를 적는다(soak).
종료 코드: 0 판정 항목(오류·복원 실패·교차 누출 0, 감사 줄 = 요청, 모두 가림, 끝난 뒤 볼트 세션·빌려 간 연결 0, 표본 8개 이상이면 RSS 증가 10% 미만·
열린 파일 증가 없음)을 모두 통과 / 1 그 밖
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import resource
import secrets
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.vault import TokenVault  # noqa: E402
from tests.conftest import free_port, serve  # noqa: E402

KEY, ADMIN = "load-key", "load-admin"
APIS = ("chat", "messages", "responses")
PHONE = re.compile(r"010-2\d{3}-\d{4}")              # 이 스크립트가 만드는 원래 번호의 꼴
# 이미지의 실행 명령(gateway/Dockerfile CMD)과 같은 서버 설정. 이미지에 없는 uvloop·httptools는 쓰지 않는다
SERVER_ARGS = ("--loop", "asyncio", "--http", "h11", "--no-access-log", "--limit-concurrency", "1000",
               "--timeout-graceful-shutdown", "25")


def request_for(api: str, phone: str, stream: bool) -> tuple[str, dict, dict]:
    text = f"제 번호는 {phone}입니다. 확인 부탁드립니다."
    model = "stub-stream" if stream else "stub-model"
    if api == "chat":
        return "/v1/chat/completions", {"authorization": f"Bearer {KEY}"}, {
            "model": model, "stream": stream, "messages": [{"role": "user", "content": text}]}
    if api == "messages":
        return "/v1/messages", {"x-api-key": KEY, "anthropic-version": "2023-06-01"}, {
            "model": model, "stream": stream, "max_tokens": 64, "messages": [{"role": "user", "content": text}]}
    return "/v1/responses", {"authorization": f"Bearer {KEY}"}, {"model": model, "stream": stream, "input": text}


def full_text(api: str, obj: dict) -> str | None:
    """전체 텍스트를 다시 담은 이벤트(Responses `response.output_text.done`) — 조각과 따로 복원되므로 따로 본다."""
    return obj.get("text") if api == "responses" and obj.get("type") == "response.output_text.done" else None


def delta(api: str, obj: dict) -> str:
    """스트림 이벤트 하나의 내용 조각."""
    if api == "chat":
        return "".join((c.get("delta") or {}).get("content") or "" for c in obj.get("choices") or [])
    if api == "messages":
        return (obj.get("delta") or {}).get("text", "") if obj.get("type") == "content_block_delta" else ""
    return obj.get("delta", "") if obj.get("type") == "response.output_text.delta" else ""


class Run:
    def __init__(self, surrogate_key: str | None) -> None:
        self.lat: dict[str, list[float]] = {"plain": [], "ttft": [], "stream": []}
        self.ok = self.errors = self.restore_fail = self.leaks = 0
        self.sent: set[str] = set()
        self.error_kinds: dict[str, int] = {}
        # 게이트웨이와 같은 대체값 키 — 요청마다 그 번호의 가짜 번호를 계산해, 남은 가짜 번호(복원 실패)와 남의 번호(누출)를 가른다
        self.vault = TokenVault(key=surrogate_key.encode()) if surrogate_key else None

    def error(self, kind: str) -> None:
        self.errors += 1
        self.error_kinds[kind] = self.error_kinds.get(kind, 0) + 1

    def check(self, phone: str, texts: list[str]) -> None:
        """복원(게이트웨이 경로만 — 스텁 직접은 가리지 않는다)과 교차 누출(다른 요청이 보낸 원래 번호). `texts`의 각 텍스트에 원래 번호가 있어야 한다."""
        fake = self.vault.token_for("load", "phone", phone) if self.vault else None
        found = {m for t in texts for m in PHONE.findall(t)}
        if fake is not None and (any(phone not in t for t in texts) or any(fake in t for t in texts)):
            self.restore_fail += 1
        if (found - {phone, fake}) & self.sent:
            self.leaks += 1


async def one(client: httpx.AsyncClient, run: Run, wid: int, n: int, stream: bool) -> None:
    api = APIS[(wid + n) % len(APIS)]
    phone = f"010-{2000 + wid:04d}-{1000 + n % 9000:04d}"
    run.sent.add(phone)
    path, headers, body = request_for(api, phone, stream)
    t0 = time.perf_counter()
    try:
        async with client.stream("POST", path, headers=headers, json=body) as r:
            if r.status_code != 200:
                await r.aread()
                run.error(f"http {r.status_code}")
                return
            if not stream:
                texts = [(await r.aread()).decode("utf-8")]
                run.lat["plain"].append(time.perf_counter() - t0)
            else:
                buf, parts, fulls, ttft = b"", [], [], None
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    while b"\n\n" in buf:
                        event, buf = buf.split(b"\n\n", 1)
                        for line in event.split(b"\n"):
                            if line.startswith(b"data:") and line[5:].strip() not in (b"", b"[DONE]"):
                                obj = json.loads(line[5:])
                                piece = delta(api, obj)
                                if piece:
                                    ttft = ttft if ttft is not None else time.perf_counter() - t0
                                    parts.append(piece)
                                if (whole := full_text(api, obj)) is not None:
                                    fulls.append(whole)
                run.lat["stream"].append(time.perf_counter() - t0)
                if ttft is not None:
                    run.lat["ttft"].append(ttft)
                texts = ["".join(parts), *fulls]
    except (httpx.HTTPError, ValueError) as exc:
        run.error(type(exc).__name__)
        return
    run.ok += 1
    run.check(phone, texts)


async def load(base: str, streams: int, plain: int, duration: float, surrogate_key: str | None) -> tuple[Run, float]:
    """`surrogate_key`가 있으면 게이트웨이 경로다 — 복원·누출을 그 키로 판정한다. 없으면 스텁 직접(기준선)."""
    run = Run(surrogate_key)
    until = time.perf_counter() + duration

    async def worker(wid: int, stream: bool) -> None:
        # 작업자마다 클라이언트(연결) 하나 — 클라이언트 하나를 함께 쓰면 httpcore 공유 풀의 배정 겹침(D-122)을 부하 생성기 쪽에서 잰다
        async with httpx.AsyncClient(base_url=base, timeout=60, limits=httpx.Limits(max_connections=1)) as client:
            n = 0
            while time.perf_counter() < until:
                await one(client, run, wid, n, stream)
                n += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(worker(w, w < streams) for w in range(streams + plain)))
    return run, time.perf_counter() - t0


def rss_mib(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return round(int(out or 0) / 1024, 1)


def cpu_s(pid: int) -> float:
    """프로세스의 누적 CPU 시간(초) — `ps -o time=`([[일-]시:]분:초)."""
    out = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    days, _, hms = out.rpartition("-")
    secs = sum(float(x) * 60 ** i for i, x in enumerate(reversed(hms.split(":")))) if hms else 0.0
    return secs + int(days or 0) * 86400


def open_files(pid: int) -> int:
    proc = Path(f"/proc/{pid}/fd")
    if proc.exists():                                   # Linux
        return len(list(proc.iterdir()))
    out = subprocess.run(["lsof", "-p", str(pid)], capture_output=True, text=True).stdout   # macOS
    return max(len(out.splitlines()) - 1, 0)


def gauge(text: str, name: str) -> int:
    """레이블별 게이지의 합(정책마다·상류마다)."""
    return sum(int(v) for v in re.findall(rf"^{name}(?:{{[^}}]*}})? (\d+)$", text, re.M))


def sample(gateway: str, pid: int, t: float) -> dict:
    metrics = httpx.get(gateway + "/__gateway/metrics", headers={"authorization": f"Bearer {ADMIN}"}, timeout=10).text
    return {"t": round(t, 1), "rss_mib": rss_mib(pid), "open_files": open_files(pid), "cpu_s": cpu_s(pid),
            "vault_sessions": gauge(metrics, "gateway_vault_sessions"),
            "upstream_in_use": gauge(metrics, "gateway_upstream_connections_in_use")}


async def sampler(gateway: str, pid: int, every: float, samples: list[dict], t0: float) -> None:
    """표본 하나가 실패해도 멈추지 않는다 — 실패는 표본에 적고 판정이 센다."""
    while True:
        t = time.perf_counter() - t0
        try:
            samples.append(await asyncio.to_thread(sample, gateway, pid, t))
        except Exception as exc:
            samples.append({"t": round(t, 1), "error": type(exc).__name__})
        await asyncio.sleep(every)


def pct(values: list[float], q: int) -> float:
    if len(values) < 2:
        return values[0] if values else float("nan")
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


def row(name: str, where: str, values: list[float]) -> str:
    ms = [x * 1000 for x in values]
    return f"| {name} | {where} | {len(ms)} | {pct(ms, 50):.1f} | {pct(ms, 95):.1f} | {pct(ms, 99):.1f} |"


def audit(log: Path) -> dict:
    """감사 줄 — 게이트웨이 자체 처리 시간(gateway_ms, 초, 200만, 스트리밍과 나눠서), 200이 아닌 줄의 (상태, error) 건수,
    줄 수와 가짜 값을 발급한 200 줄 수(정말 가렸는가). 회전하지 않게 띄운다(GATEWAY_LOG_MAX_BYTES=0)."""
    lat: dict[str, list[float]] = {"plain": [], "stream": []}
    errors: dict[str, int] = {}
    lines = masked = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        lines += 1
        if rec.get("status") != 200:
            key = f"{rec.get('status')} {rec.get('error')}"
            errors[key] = errors.get(key, 0) + 1
            continue
        masked += rec.get("pii_issued", 0) > 0
        if rec.get("gateway_ms") is not None:
            lat["stream" if rec.get("model") == "stub-stream" else "plain"].append(rec["gateway_ms"] / 1000)
    return {"lat": lat, "errors": errors, "lines": lines, "masked": masked}


def main() -> int:
    signal.signal(signal.SIGTERM, signal.default_int_handler)   # kill(SIGTERM)도 Ctrl-C처럼 — 아래 finally가 서버를 끄고 임시 폴더를 지운다(D-124)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=float, default=60, help="부하 시간(초)")
    ap.add_argument("--streams", type=int, default=50, help="스트리밍 작업자 수")
    ap.add_argument("--plain", type=int, default=50, help="비스트리밍 작업자 수")
    ap.add_argument("--delay-ms", type=float, default=300, help="스텁의 첫 바이트 전 지연")
    ap.add_argument("--chunk-ms", type=float, default=20, help="스텁의 스트림 조각 사이 지연")
    ap.add_argument("--sample", type=float, default=10, help="프로세스·볼트 표본 간격(초)")
    ap.add_argument("--max-connections", type=int, default=100, help="게이트웨이의 상류 연결 수(GATEWAY_MAX_CONNECTIONS) — 작업자보다 적게 주면 대기·넘겨주기 경로를 지난다")
    ap.add_argument("--baseline", action=argparse.BooleanOptionalAction, default=True, help="같은 부하를 스텁에 바로 보낸 기준선도 잰다")
    ap.add_argument("--out", type=Path, help="원자료 JSON")
    a = ap.parse_args()
    if not 0 < a.streams + a.plain <= 1000:
        ap.error("작업자는 1~1,000개다(번호 꼴 010-2www-nnnn)")
    for name in [k for k in os.environ if k.startswith(("GATEWAY_", "TARGET_", "UVICORN_"))]:
        del os.environ[name]                 # 셸의 게이트웨이·uvicorn 설정(UVICORN_ENV_FILE·HOST 등)이 측정에 섞이지 않게 — 아래에서 다 정한다
    key = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory() as tmp:
        sp, gp = free_port(), free_port()
        stub, gateway = f"http://127.0.0.1:{sp}", f"http://127.0.0.1:{gp}"
        log = Path(tmp) / "gateway.jsonl"
        procs = [serve("tests.stub_target:app", sp, {"STUB_DELAY_MS": str(a.delay_ms), "STUB_CHUNK_MS": str(a.chunk_ms)},
                       args=("--no-access-log",))]
        try:
            procs.append(serve("gateway.main:app", gp, {
                "TARGET_URL": stub, "GATEWAY_LOG_PATH": str(log), "GATEWAY_LOG_MAX_BYTES": "0", "GATEWAY_CLIENT_KEYS": f"load={KEY}",
                "GATEWAY_ADMIN_KEY": ADMIN, "GATEWAY_SURROGATE_KEY": key, "GATEWAY_PII": "mask", "GATEWAY_INJECTION": "observe",
                "GATEWAY_MAX_CONNECTIONS": str(a.max_connections),
            }, probe="/__gateway/health", args=SERVER_ARGS))
            # D-124: 측정하는 동안 열어 본다(폴링은 감사·지표에 들지 않는다). 결과 표는 끝에 한꺼번에 찍으므로 표가 깨지지 않는다
            print(f"대시보드 {gateway}/__gateway/dashboard · 관리 키 {ADMIN}", flush=True)
            pid = procs[-1].pid
            base = asyncio.run(load(stub, a.streams, a.plain, a.duration, None))[0] if a.baseline else None
            stub_cpu0, me0 = cpu_s(procs[0].pid), resource.getrusage(resource.RUSAGE_SELF)

            async def measured() -> tuple[Run, float, list[dict]]:
                samples: list[dict] = []
                t0 = time.perf_counter()
                task = asyncio.create_task(sampler(gateway, pid, a.sample, samples, t0))
                run, took = await load(gateway, a.streams, a.plain, a.duration, key)
                task.cancel()
                await asyncio.sleep(1)                   # 끝난 스트림의 볼트 해제가 끝나게
                samples.append({**await asyncio.to_thread(sample, gateway, pid, time.perf_counter() - t0), "after": True})
                return run, took, samples

            run, took, samples = asyncio.run(measured())
            me1 = resource.getrusage(resource.RUSAGE_SELF)
            cpu_other = {"stub": (cpu_s(procs[0].pid) - stub_cpu0) / took,
                         "client": (me1.ru_utime + me1.ru_stime - me0.ru_utime - me0.ru_stime) / took}
            logged = audit(log)
        finally:
            for p in reversed(procs):
                p.terminate()
                p.wait(30)

    total = run.ok + run.errors
    good = [x for x in samples if "error" not in x]
    during = [x for x in good if not x.get("after")][1:]            # 첫 표본은 워밍업
    q = max(len(during) // 4, 1)
    growth = statistics.mean(x["rss_mib"] for x in during[-q:]) / statistics.mean(x["rss_mib"] for x in during[:q]) - 1 if during else 0.0
    files_up = max(x["open_files"] for x in during[-q:]) - max(x["open_files"] for x in during[:q]) if during else 0
    after = samples[-1]
    sample_errors = len(samples) - len(good)
    gw_cpu = during[-1]["cpu_s"] - good[0]["cpu_s"] if during else 0.0
    span = during[-1]["t"] - good[0]["t"] if during else 0.0
    print(f"## 부하 — {a.duration:.0f}초, 스트림 {a.streams} + 비스트리밍 {a.plain}, 스텁 지연 {a.delay_ms:.0f}ms·조각 사이 {a.chunk_ms:.0f}ms, "
          f"상류 연결 {a.max_connections}\n")
    print(f"요청 {total}건(초당 {total / took:.1f}), 오류 {run.errors}{' ' + str(run.error_kinds) if run.error_kinds else ''}, "
          f"복원 실패 {run.restore_fail}, 교차 누출 {run.leaks}"
          + (f", 기준선 오류 {base.errors}{' ' + str(base.error_kinds) if base.error_kinds else ''}" if base else "") + "\n")
    print(f"감사 줄 {logged['lines']}(요청 {total}), 가짜 값을 발급한 200 줄 {logged['masked']}(200 응답 {run.ok})"
          + (f", 200 아닌 줄 {logged['errors']}" if logged["errors"] else "") + "\n")
    if span:
        print(f"CPU 사용률(코어 1개 = 100%) — 게이트웨이 {gw_cpu / span:.0%}(표본 구간), 스텁 {cpu_other['stub']:.0%}, 부하 생성기 {cpu_other['client']:.0%}. "
              f"게이트웨이 CPU 요청당 {gw_cpu * 1000 / max(total * span / took, 1):.1f}ms\n")
    print("| 구간(ms) | 경로 | 건수 | p50 | p95 | p99 |\n|---|---|---|---|---|---|")
    for name, k in (("비스트리밍 응답", "plain"), ("스트림 첫 내용 조각", "ttft"), ("스트림 끝", "stream")):
        print(row(name, "게이트웨이", run.lat[k]))
        if base is not None:
            print(row(name, "스텁 직접", base.lat[k]))
    print(row("감사 gateway_ms", "비스트리밍", logged["lat"]["plain"]))
    print(row("감사 gateway_ms", "스트리밍(요청 쪽만)", logged["lat"]["stream"]))
    print(f"\n표본 {len(samples)}개(실패 {sample_errors}) — RSS {good[0]['rss_mib']} → {after.get('rss_mib')} MiB(증가율 {growth:+.1%}, "
          f"마지막 4분의 1 ÷ 처음 4분의 1, 워밍업 뺌), 부하 중 열린 파일 증가 {files_up:+d}(마지막 4분의 1 최대 − 처음 4분의 1 최대), "
          f"볼트 세션 최대 {max(x['vault_sessions'] for x in good)} · 끝난 뒤 {after.get('vault_sessions')}, 끝난 뒤 빌려 간 상류 연결 {after.get('upstream_in_use')}")
    checks = {
        "오류 0": run.errors == 0, "복원 실패 0": run.restore_fail == 0, "교차 누출 0": run.leaks == 0,
        "감사 줄 = 요청": logged["lines"] == total, "200 응답은 모두 가렸다": logged["masked"] == run.ok,
        "표본 실패 0": sample_errors == 0, "끝난 뒤 볼트 세션 0": after.get("vault_sessions") == 0,
        "끝난 뒤 빌려 간 상류 연결 0": after.get("upstream_in_use") == 0,
        "RSS 증가 10% 미만": len(during) < 8 or growth < 0.10, "열린 파일이 늘지 않는다": len(during) < 8 or files_up <= 5,
    }
    print("판정: " + ", ".join(f"{name} {'통과' if ok else '실패'}" for name, ok in checks.items()))
    if a.out:
        a.out.write_text(json.dumps({
            "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(a).items()}, "requests": total, "seconds": took,
            "errors": run.errors, "error_kinds": run.error_kinds, "restore_fail": run.restore_fail, "leaks": run.leaks,
            "audit_errors": logged["errors"], "audit_lines": logged["lines"], "audit_masked": logged["masked"],
            "baseline_errors": base.error_kinds if base else None, "cpu_other": cpu_other,
            "rss_growth": growth, "open_files_growth": files_up, "samples": samples, "checks": checks,
            "latency_ms": {k: [round(x * 1000, 2) for x in v] for k, v in run.lat.items()},
            "baseline_ms": {k: [round(x * 1000, 2) for x in v] for k, v in base.lat.items()} if base else None,
            "audit_gateway_ms": {k: [round(x * 1000, 2) for x in v] for k, v in logged["lat"].items()},
        }, ensure_ascii=False), encoding="utf-8")
    return 0 if all(checks.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
