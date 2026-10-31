"""D-122(PLAN 15단계): 부하 스크립트 스모크(배선이 썩지 않게)와 볼트 세션 지표."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from tests.conftest import ADMIN

ROOT = Path(__file__).resolve().parents[1]
CHAT = "/v1/chat/completions"


def test_l5_load_script_smoke(tmp_path):
    out = tmp_path / "load.json"
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "load.py"), "--duration", "2", "--streams", "3", "--plain", "3",
                        "--delay-ms", "20", "--chunk-ms", "2", "--sample", "1", "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["requests"] > 10 and r["errors"] == r["restore_fail"] == r["leaks"] == 0
    assert r["latency_ms"]["plain"] and r["latency_ms"]["ttft"] and r["baseline_ms"]["plain"] and r["audit_gateway_ms"]["plain"]
    assert r["samples"][-1]["vault_sessions"] == 0 and r["samples"][-1]["open_files"] > 0


def flags(args: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    i = 0
    while i < len(args):
        value = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else None
        out[args[i]] = value
        i += 2 if value is not None else 1
    return out


def test_l1_load_server_matches_the_image():
    """부하를 거는 게이트웨이의 서버 설정이 이미지의 실행 명령과 같다 — 이미지를 바꾸고 측정을 잊지 않게."""
    spec = importlib.util.spec_from_file_location("load", ROOT / "scripts" / "load.py")
    load = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(load)
    cmd = json.loads(re.search(r"^CMD (\[.*\])$", (ROOT / "gateway" / "Dockerfile").read_text(encoding="utf-8"), re.M)[1])
    image = flags(cmd[2:])
    del image["--host"], image["--port"]
    assert image.items() <= flags(list(load.SERVER_ARGS)).items()
    assert {"--loop": "asyncio", "--http": "h11"}.items() <= flags(list(load.SERVER_ARGS)).items()   # 이미지에 uvloop·httptools가 없다


def gauge(gateway: str, name: str) -> int:
    """레이블별 게이지의 합(정책마다·상류마다)."""
    text = httpx.get(gateway + "/__gateway/metrics", headers=ADMIN).text
    return sum(int(v) for v in re.findall(rf"^{name}{{[^}}]*}} (\d+)$", text, re.M))


def sessions(gateway: str) -> int:
    return gauge(gateway, "gateway_vault_sessions")


def in_use(gateway: str) -> int:
    return gauge(gateway, "gateway_upstream_connections_in_use")


def test_l3_vault_sessions_gauge(make_stack):
    """상류가 답하는 동안(stub-slow, 2초) 가린 요청의 세션 1, 끝나면 0."""
    s = make_stack(GATEWAY_DETECTORS="pii_mask")
    assert sessions(s.gateway) == 0
    done: list[httpx.Response] = []
    body = {"model": "stub-slow", "messages": [{"role": "user", "content": "제 번호는 010-2345-6789입니다"}]}
    t = threading.Thread(target=lambda: done.append(httpx.post(s.gateway + CHAT, json=body, timeout=10)))
    t.start()
    seen, deadline = 0, time.monotonic() + 1.5
    while not seen and time.monotonic() < deadline:
        seen = sessions(s.gateway)
        time.sleep(0.05)
    t.join(10)
    assert seen == 1 and "010-2345-6789" in done[0].text
    assert sessions(s.gateway) == 0


async def abort_after(port: int, body: bytes, wait: float) -> None:
    """원시 소켓으로 요청을 보내고 `wait`초 뒤 끊는다 — 응답은 읽지 않는다."""
    import asyncio
    _, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"POST " + CHAT.encode() + b" HTTP/1.1\r\nHost: gw\r\nContent-Type: application/json\r\n"
                 + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    await writer.drain()
    await asyncio.sleep(wait)
    writer.transport.abort()


def test_l2_client_disconnects_leave_no_sessions_and_one_audit_line_each(make_stack, monkeypatch):
    """클라이언트가 어느 때 끊어도(상류를 기다리는 중·머리를 받기 전·스트림 중) 대체값 세션이 남지 않고 감사 줄은 요청마다 하나다.
    끊김은 앱 작업의 anyio 취소로 온다 — 정리 코드의 await마다 다시 터지므로 정리는 취소를 막고 해야 한다."""
    import asyncio
    from tests import stub_target
    monkeypatch.setattr(stub_target, "DELAY", 0.2)
    monkeypatch.setattr(stub_target, "CHUNK", 0.02)
    s = make_stack(GATEWAY_DETECTORS="pii_mask")
    port = int(s.gateway.rsplit(":", 1)[1])
    text = "제 번호는 010-2345-6789입니다"
    bodies = [json.dumps({"model": m, "stream": m == "stub-stream", "messages": [{"role": "user", "content": text}]}).encode()
              for m in ("stub-stream", "stub-model")]
    waits = [0.0, 0.05, 0.15, 0.19, 0.21, 0.25, 0.4]

    async def burst() -> None:
        for _ in range(3):
            await asyncio.gather(*(abort_after(port, b, w) for w in waits for b in bodies))

    asyncio.run(burst())
    deadline = time.monotonic() + 10
    while (sessions(s.gateway) or in_use(s.gateway) or len(s.log_lines()) < 3 * len(waits) * len(bodies)) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert sessions(s.gateway) == 0
    assert in_use(s.gateway) == 0                              # 빌려 간 상류 연결이 모두 돌아왔다
    lines = s.log_lines()
    assert len(lines) == 3 * len(waits) * len(bodies)
    # 스트림은 0.2초 + 조각 33개 × 0.02초라 0.4초 안에 끊으면 언제나 도중이다 — 정상 완료(error 없음)로 남으면 안 된다
    assert all(x["error"] for x in lines if x["model"] == "stub-stream")


# ---------- 리뷰(D-122 §6) 수정의 회귀 ----------

def test_pool_hands_released_connection_to_the_first_waiter():
    """돌려받은 연결은 기다리던 순서대로 넘긴다 — 새로 온 요청이 가로채지 않는다(리뷰 C04·C10)."""
    import asyncio
    from gateway.relay import UpstreamPool

    async def run() -> None:
        pool = UpstreamPool(object, 1, wait=1)
        first = await pool.acquire()
        b = asyncio.create_task(pool.acquire())
        c = asyncio.create_task(pool.acquire())
        await asyncio.sleep(0)
        pool.release(first)
        d = asyncio.create_task(pool.acquire())              # 넘겨준 직후에 온 요청
        await asyncio.sleep(0)
        assert b.done() and b.result() is first and not c.done() and not d.done()
        pool.release(b.result())
        await asyncio.sleep(0)
        assert c.done() and not d.done() and pool.in_use == 1
        pool.release(c.result())
        assert (await d) is first
        pool.release(first)
        assert pool.in_use == 0

    asyncio.run(run())


def test_pool_waiter_timeout_leaves_no_trace():
    import asyncio
    import pytest
    from gateway.relay import UpstreamPool

    async def run() -> None:
        pool = UpstreamPool(object, 1, wait=0.05)
        held = await pool.acquire()
        with pytest.raises(TimeoutError):
            await pool.acquire()
        pool.release(held)                                   # 시간이 다 된 대기자에게 가지 않고 쉬는 연결이 된다
        assert pool.in_use == 0 and (await pool.acquire()) is held

    asyncio.run(run())


def test_client_construction_errors_fail_startup(monkeypatch):
    """첫 연결은 기동 때 만든다 — 클라이언트를 만들 수 없는 설정이면 기동이 실패한다(리뷰 C07)."""
    import asyncio
    import pytest
    from gateway import main
    from gateway.settings import Settings

    def broken(*args: object) -> None:
        raise ValueError("bad proxy")

    monkeypatch.setattr(main, "_connection", broken)
    app = main.create_app(Settings(auth_off=True, pii="detect"))

    async def boot() -> None:
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(ValueError, match="bad proxy"):
        asyncio.run(boot())


def test_non_ascii_request_headers_are_forwarded_and_leak_nothing(make_stack):
    """한국어가 든 User-Agent·idempotency-key — 예전에는 httpx가 ascii로 묶다 500, 풀은 연결을 잃었다(리뷰 C01·C06)."""
    s = make_stack(GATEWAY_MAX_CONNECTIONS="1")
    ua = "내앱/1.0".encode()
    r = httpx.get(s.gateway + "/v1/models", headers={"user-agent": ua})
    assert r.status_code == 200 and r.json()["gateway_test"]["headers"]["user-agent"] == ua.decode("latin-1")
    for _ in range(3):                                       # 연결 하나짜리 풀 — 잃었으면 둘째부터 503
        r = httpx.post(s.gateway + CHAT, headers={"idempotency-key": "키-1".encode()},
                       json={"model": "stub-model", "messages": [{"role": "user", "content": "hi"}]}, timeout=10)
        assert r.status_code == 200
    assert in_use(s.gateway) == 0


def test_upstream_response_headers_are_copied_as_bytes():
    """상류가 UTF-8 값을 준 허용 헤더 — str로 다시 묶으면 latin-1 밖 문자에서 오류였다(리뷰 C02·C09)."""
    from fastapi import Response
    from gateway.relay import _pass_headers
    upstream = httpx.Response(200, headers=[(b"cache-control", "max-age=1 ✓".encode()), (b"set-cookie", b"a=b")])
    response = Response()
    _pass_headers(upstream, response)
    assert (b"cache-control", "max-age=1 ✓".encode()) in response.raw_headers
    assert all(k != b"set-cookie" for k, _ in response.raw_headers)


def test_oversized_body_is_audited_with_its_reason(make_stack):
    s = make_stack(GATEWAY_MAX_BODY_BYTES="100")
    r = httpx.post(s.gateway + CHAT, json={"model": "stub-model", "messages": [{"role": "user", "content": "가" * 200}]})
    assert r.status_code == 413
    (line,) = [x for x in s.log_lines() if x["request_id"] == r.headers["x-gateway-request-id"]]
    assert line["error"] == "request_too_large"


def test_internal_error_on_messages_uses_the_anthropic_format(make_stack):
    from tests.chain_app import REGISTRY
    s = make_stack(REGISTRY, GATEWAY_DETECTORS="test_boom")
    r = httpx.post(s.gateway + "/v1/messages", json={"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 500 and r.json() == {"type": "error", "error": {"type": "api_error", "message": "internal gateway error"}}
    assert r.headers["x-gateway-request-id"]


def test_key_values_are_stripped(tmp_path):
    """secret.env·`$(cat 파일)`의 줄 끝 공백이 키에 붙으면 기동 검사는 통과하고 요청마다 상류 401이었다(리뷰 C12)."""
    from gateway.settings import Settings
    config = tmp_path / "gateway.toml"
    config.write_text('[upstreams.messages]\nbase_url = "http://a"\nkey_env = "ANT"\n', encoding="utf-8")
    s = Settings.from_env({"GATEWAY_CONFIG": str(config), "ANT": " sk-ant \n", "GATEWAY_UPSTREAM_KEY": "sk-up ",
                           "GATEWAY_ADMIN_KEY": "adm\n", "GATEWAY_SURROGATE_KEY": " " + "k" * 32 + " "})
    assert (s.upstream("messages").key, s.upstream_key, s.admin_key, s.surrogate_key) == ("sk-ant", "sk-up", "adm", "k" * 32)
