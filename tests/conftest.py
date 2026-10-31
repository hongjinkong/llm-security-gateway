"""테스트 공용 도구 — 스텁 타겟과 게이트웨이를 임시 포트에 띄운다.

D-118: `make_stack`은 둘 다 **이 프로세스의 스레드에서** uvicorn으로 띄운다 — 게이트웨이는 `create_app(Settings.from_env(env))`라
환경변수 대신 dict를 넘기고(개발자 환경이 새어 들지 않는다), 프로세스를 띄우는 비용이 없다. 실제 HTTP·실제 스트리밍 그대로다.
`serve`(서브프로세스)는 다른 작업 트리·stdout·`python -m uvicorn` 자체를 보는 테스트와 스크립트만 쓴다.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pytest
import uvicorn

from gateway.main import create_app
from gateway.settings import DETECTOR_REGISTRY, Registry, Settings
from tests.stub_target import app as stub_app

ADMIN_KEY = "test-admin-key"   # make_stack이 띄우는 게이트웨이의 관리 키(D-109) — info·metrics를 본다
ADMIN = {"Authorization": f"Bearer {ADMIN_KEY}"}
SURROGATE_KEY = "test-surrogate-key-0123456789abcdef"   # make_stack의 결정적 대체값 키(D-111) — mask 모드는 이게 없으면 뜨지 않는다


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app: str, port: int, env: dict | None = None, probe: str = "/", cwd: Path | None = None,
          args: tuple[str, ...] = ()) -> subprocess.Popen:
    """기동 확인용 probe 경로는 감사 로그를 오염시키지 않는 곳으로 고른다.
    게이트웨이는 /__gateway/health(로그 제외 경로)를 쓴다. `args`는 uvicorn에 더 줄 인자(D-122 — 이미지와 같은 서버 설정)."""
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app, "--port", str(port), "--log-level", "warning", *args],
        env={**os.environ, **(env or {})},
        cwd=cwd,   # 다른 작업 트리의 게이트웨이(D-114 옛 팔)
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


def start(app, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    """앱을 이 프로세스의 스레드에서 띄운다. lifespan이 실패하면(기동 거부) uvicorn이 멈추므로 '기동 실패'로 알린다."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, log_level="warning",
                                           access_log=False, timeout_graceful_shutdown=2))
    thread = threading.Thread(target=_run, args=(server,), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("게이트웨이 기동 실패")
        if time.monotonic() > deadline:
            raise RuntimeError("기동 시간 초과")
        time.sleep(0.005)
    return server, thread


def _run(server: uvicorn.Server) -> None:
    try:
        server.run()
    except SystemExit:
        pass          # 기동 실패를 uvicorn이 sys.exit로 알린다 — 스레드에서는 start()가 server.started로 본다


def install(app, settings: Settings, chain, client: httpx.AsyncClient | None = None) -> None:
    """lifespan 없이 프로세스 안 앱에 요청 처리 상태를 넣는다(D-118·D-119): 정책은 default 하나, 세 API가 상류 client 하나를 쓴다.
    client는 연결 하나짜리 풀로 감싼다(D-122) — 동시 요청은 하나씩, 빈 연결 대기는 client의 pool 시간 제한. 인증·감사·레이트리밋은 호출자가 넣는다."""
    from gateway.relay import UpstreamClient, UpstreamPool
    from gateway.settings import API_NAMES
    app.state.settings = settings
    app.state.policies = {"default": settings}
    app.state.chains = {"default": chain}
    app.state.chain = chain
    if client is not None:
        pool = UpstreamPool(lambda: client, 1, wait=client.timeout.pool or 5)
        app.state.upstreams = dict.fromkeys(API_NAMES, UpstreamClient(pool, ""))


def stop(servers: list[tuple[uvicorn.Server, threading.Thread]]) -> None:
    for server, _ in servers:
        server.should_exit = True
    for _, thread in servers:
        thread.join(10)


@dataclass
class Stack:
    target: str      # 스텁 타겟 URL (직접 호출용)
    gateway: str     # 게이트웨이 URL
    log_path: Path   # 감사 로그 경로

    def info(self) -> dict:
        """/__gateway/info — 버전·코드 지문·상류·검사기(D-109). 관리 키가 필요하다."""
        r = httpx.get(f"{self.gateway}/__gateway/info", headers=ADMIN)
        assert r.status_code == 200, r.text
        return r.json()

    def log_lines(self) -> list[dict]:
        import json
        if not self.log_path.exists():
            return []
        return [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines() if x]


@pytest.fixture(scope="module")
def make_stack(tmp_path_factory):
    """스텁 타겟 + 게이트웨이 한 벌을 띄우는 공장. 환경변수(dict)를 바꿔 여러 벌 띄울 수 있다.
    `registry`로 시험용 검사기를 더한다(tests/chain_app.py). `GATEWAY_DETECTORS`는 환경변수가 아니라 `Settings.detectors`로 넘긴다(D-118)."""
    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def _make(registry: Registry = DETECTOR_REGISTRY, **env: str) -> Stack:
        log_path = tmp_path_factory.mktemp("logs") / "gateway.jsonl"
        tp, gp = free_port(), free_port()
        servers.append(start(stub_app, tp))
        # 기본은 검사기 없음(4-A)·무인증(로컬 실험). 인증을 시험하는 테스트만 GATEWAY_CLIENT_KEYS를 넘긴다(D-107 A).
        # 값이 None이면 "그 변수를 아예 주지 않는다"(제품 기본값을 시험할 때 — D-107 D).
        base = {"GATEWAY_DETECTORS": ""} if "GATEWAY_DETECTORS" not in env else {}
        if "GATEWAY_ADMIN_KEY" not in env:
            base["GATEWAY_ADMIN_KEY"] = ADMIN_KEY
        if "GATEWAY_SURROGATE_KEY" not in env:
            base["GATEWAY_SURROGATE_KEY"] = SURROGATE_KEY
        if "GATEWAY_CLIENT_KEYS" not in env and "GATEWAY_AUTH" not in env:
            base["GATEWAY_AUTH"] = "off"
        full = {"TARGET_URL": f"http://127.0.0.1:{tp}", "GATEWAY_LOG_PATH": str(log_path), **base,
                **{k: v for k, v in env.items() if v is not None}}
        detectors = full.pop("GATEWAY_DETECTORS", None)
        try:
            settings = Settings.from_env(full)
        except ValueError as exc:
            raise RuntimeError(f"게이트웨이 기동 실패: {exc}") from exc
        if detectors is not None:
            settings = replace(settings, detectors=tuple(x.strip() for x in detectors.split(",") if x.strip()))
        servers.append(start(create_app(settings, registry), gp))
        return Stack(f"http://127.0.0.1:{tp}", f"http://127.0.0.1:{gp}", log_path)

    try:
        yield _make
    finally:
        stop(servers)


@pytest.fixture(scope="module")
def stack(make_stack) -> Stack:
    """검사기 없는 기본 게이트웨이."""
    return make_stack()
