"""서브프로세스로 uvicorn 앱을 띄우는 도구 — pytest 없이도 import된다(D-131: 데모 이미지가 `web/app.py`와 함께 싣는다).

`tests.conftest`가 다시 내보낸다 — 테스트는 예전처럼 `from tests.conftest import free_port, serve`로 쓴다.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app: str, port: int, env: dict | None = None, probe: str = "/", cwd: Path | None = None,
          args: tuple[str, ...] = ()) -> subprocess.Popen:
    """기동 확인용 probe 경로는 감사 로그를 오염시키지 않는 곳으로 고른다.
    게이트웨이는 /__gateway/health(로그 제외 경로)를 쓴다. `args`는 uvicorn에 더 줄 인자(D-122 — 이미지와 같은 서버 설정)."""
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning", *args],   # 셸의 UVICORN_HOST보다 앞선다
        env={**os.environ, **(env or {})},
        cwd=cwd,   # 다른 작업 트리의 게이트웨이(D-114 옛 팔)
    )
    try:
        for _ in range(100):  # 최대 10초 대기
            try:
                httpx.get(f"http://127.0.0.1:{port}{probe}", timeout=0.5)
                return p
            except httpx.RequestError:
                if p.poll() is not None:
                    raise RuntimeError(f"{app} 기동 실패")
                time.sleep(0.1)
        raise RuntimeError(f"{app} 기동 시간 초과")
    except BaseException:
        p.kill()      # 호출자의 정리 목록에 들기 전이다 — 시간 초과·Ctrl-C·SIGTERM에 끄지 않으면 고아가 되어 포트와 부모의 stdout 파이프를 쥔다(D-124)
        p.wait()
        raise
