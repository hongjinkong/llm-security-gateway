"""테스트 공용 도구 — 스텁 타겟과 게이트웨이를 임시 포트에 띄운다."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app: str, port: int, env: dict | None = None, probe: str = "/") -> subprocess.Popen:
    """기동 확인용 probe 경로는 감사 로그를 오염시키지 않는 곳으로 고른다.
    게이트웨이는 /__gateway/health(로그 제외 경로)를 쓴다."""
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app, "--port", str(port), "--log-level", "warning"],
        env={**os.environ, **(env or {})},
    )
    for _ in range(100):  # 최대 10초 대기
        try:
            httpx.get(f"http://127.0.0.1:{port}{probe}", timeout=0.5)
            return p
        except httpx.RequestError:
            if p.poll() is not None:
                raise RuntimeError(f"{app} 기동 실패")
            time.sleep(0.1)
    raise RuntimeError(f"{app} 기동 시간 초과")


@dataclass
class Stack:
    target: str      # 스텁 타겟 URL (직접 호출용)
    gateway: str     # 게이트웨이 URL
    log_path: Path   # 감사 로그 경로

    def log_lines(self) -> list[dict]:
        import json
        if not self.log_path.exists():
            return []
        return [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines() if x]


@pytest.fixture(scope="module")
def stack(tmp_path_factory) -> Stack:
    log_path = tmp_path_factory.mktemp("logs") / "gateway.jsonl"
    tp, gp = free_port(), free_port()
    t = serve("tests.stub_target:app", tp)
    g = serve("gateway.main:app", gp, {
        "TARGET_URL": f"http://127.0.0.1:{tp}",
        "GATEWAY_LOG_PATH": str(log_path),
    }, probe="/__gateway/health")
    try:
        yield Stack(f"http://127.0.0.1:{tp}", f"http://127.0.0.1:{gp}", log_path)
    finally:
        for p in (g, t):
            p.terminate()
            p.wait(10)
