"""4-A 완료 조건 검증: 게이트웨이 경유 응답 == 타겟 직접 호출 응답.

실행: pytest tests/test_passthrough.py -v
스텁 타겟과 게이트웨이를 임시 포트에 각각 띄우고, 같은 요청을 양쪽에 보내
결과가 완전히 같은지 비교한다.
"""
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app: str, port: int, env: dict | None = None):
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app, "--port", str(port), "--log-level", "warning"],
        env={**os.environ, **(env or {})},
    )
    for _ in range(100):  # 최대 10초 대기
        try:
            httpx.get(f"http://127.0.0.1:{port}/__probe", timeout=0.5)
            break
        except httpx.RequestError:
            if p.poll() is not None:
                raise RuntimeError(f"{app} 기동 실패")
            time.sleep(0.1)
    return p


@pytest.fixture(scope="module")
def servers():
    tp, gp = _free_port(), _free_port()
    target = _serve("tests.stub_target:app", tp)
    gw = _serve("gateway.main:app", gp, {"TARGET_URL": f"http://127.0.0.1:{tp}"})
    try:
        yield f"http://127.0.0.1:{tp}", f"http://127.0.0.1:{gp}"
    finally:
        for p in (gw, target):
            p.terminate()
            p.wait(10)


PATH_ = "/api/v1/workspace/demo-slug/chat"
BODY = {"message": "안녕하세요, 연차는 며칠인가요?", "mode": "query", "sessionId": "eval-abc123"}
HDR = {"Authorization": "Bearer test-key-123", "Content-Type": "application/json"}


def test_health(servers):
    _, gw = servers
    r = httpx.get(f"{gw}/__gateway/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_passthrough_identical(servers):
    """4-A의 핵심. 직접 호출과 프록시 경유가 완전히 같아야 한다."""
    target, gw = servers
    direct = httpx.post(f"{target}{PATH_}?x=1&y=한글", json=BODY, headers=HDR)
    proxied = httpx.post(f"{gw}{PATH_}?x=1&y=한글", json=BODY, headers=HDR)
    assert direct.status_code == proxied.status_code == 200
    assert direct.json() == proxied.json(), "게이트웨이가 요청/응답을 변형했다"


def test_body_and_auth_preserved(servers):
    _, gw = servers
    echo = httpx.post(f"{gw}{PATH_}", json=BODY, headers=HDR).json()["echo"]
    assert echo["body"] == BODY  # 한글·sessionId 포함 본문 무손상 (D-013)
    assert echo["auth"] == HDR["Authorization"]  # API 키가 타겟까지 전달됨
    assert echo["path"] == PATH_


def test_query_string_preserved(servers):
    _, gw = servers
    echo = httpx.post(f"{gw}{PATH_}?a=1&b=2", json=BODY, headers=HDR).json()["echo"]
    assert echo["query"] == "a=1&b=2"


def test_status_code_passthrough(servers):
    """타겟의 404를 200으로 바꾸거나 삼키지 않는다."""
    _, gw = servers
    assert httpx.get(f"{gw}/no/such/path").status_code == 404
