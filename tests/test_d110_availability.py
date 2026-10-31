"""D-110: 가용성 — 요청 한 건이 게이트웨이 전체를 멈추지 못하게 한다. 번호 V1~V7은 D-110 §4의 표와 같다."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
import pytest

from gateway.detectors.base import Inspection
from gateway.vault import HOLD_CAP, TokenVault
from tests.conftest import free_port, install, start, stop
from tests.stub_target import app as stub_app

CHAT = "/v1/chat/completions"
KEY = "sk-proj-" + "Ab1Cd2Ef3Gh4" * 13 + "Xy9Z"        # 168자 합성 키(이어 붙여 만든다 — 저장소 비밀 검사 오인 방지)
PEM = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(["MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" * 2] * 20) + "\n-----END PRIVATE KEY-----"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def phones(n: int) -> str:
    return " ".join(f"010-{1000 + i // 10000:04d}-{i % 10000:04d}" for i in range(n))


def chat(content: str, model: str = "stub-model", **extra) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": content}], **extra}


def received(stack) -> list[str]:
    return httpx.get(f"{stack.target}/__stub/received").json()["bodies"]


# ---------- V1 볼트 발급은 선형 ----------

def test_v1_vault_issuance_is_linear():
    def issue(n: int) -> float:
        v = TokenVault()
        t0 = time.perf_counter()
        for i in range(n):
            v.token_for("s", "phone", f"010-{1000 + i // 10000:04d}-{i % 10000:04d}")
        return time.perf_counter() - t0
    issue(500)                                    # 데우기
    ratio = issue(4000) / issue(1000)
    assert ratio < 8, f"1,000 → 4,000개 발급 시간 비 {ratio:.1f} (예전 약 14배)"


# ---------- V2 탐지 상한 ----------

@pytest.fixture(scope="module")
def masked(make_stack):
    return make_stack(GATEWAY_DETECTORS="pii_mask")


def test_v2_5000_unique_phones_finish_within_a_second(masked):
    t0 = time.perf_counter()
    r = httpx.post(masked.gateway + CHAT, json=chat(phones(5000)), timeout=30)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200 and elapsed < 1.0, f"{elapsed:.2f}s"
    sent = json.loads(received(masked)[-1])["messages"][0]["content"]
    assert "010-1000-0000" not in sent and "010-1000-4999" not in sent
    assert r.json()["choices"][0]["message"]["content"] == "[stub] " + phones(5000)   # 모두 복원된다


def test_v2_one_more_than_the_cap_is_413_and_never_reaches_upstream(masked):
    before = len(received(masked))
    r = httpx.post(masked.gateway + CHAT, json=chat(phones(5001)), timeout=30)
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_many_findings"
    assert len(received(masked)) == before
    (line,) = [x for x in masked.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"]]
    assert line["status"] == 413 and line["upstream_ms"] is None and line["error"] == "too_many_findings"


# ---------- V3 긴 대체값의 스트림 복원 ----------

def _stream_text(gateway: str, content: str) -> str:
    out = []
    with httpx.stream("POST", gateway + CHAT, json=chat(content, "stub-stream", stream=True), timeout=30) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                delta = json.loads(line[6:])["choices"][0]["delta"]
                out.append(delta.get("content") or "")
    return "".join(out)


@pytest.mark.parametrize("secret", [KEY, PEM], ids=["sk-proj-168", "pem"])
def test_v3_long_surrogates_split_across_chunks_are_restored(masked, secret):
    assert len(KEY) == 168 and len(PEM) > 1000
    text = _stream_text(masked.gateway, f"키는 {secret} 입니다")
    assert text == f"[stub] 키는 {secret} 입니다"            # 스텁은 3자씩 보낸다 — 대체값이 수십~수백 조각에 걸친다
    assert secret not in received(masked)[-1]


def test_v3_hold_is_bounded_by_the_longest_surrogate_issued():
    v = TokenVault()
    v.token_for("s", "phone", "010-2345-6789")
    assert v.hold("s", "x" * 1000 + "010-") == 4                  # 짧은 대체값만 발급했으면 긴 꼬리를 훑지 않는다
    tok = v.token_for("s", "secret", KEY)
    assert v.hold("s", "앞말 " + tok[:150]) == 150 and v.hold("s", "앞말 " + tok) == 0
    assert HOLD_CAP == 16 * 1024


# ---------- V4·V5·V6 인프로세스 게이트웨이 ----------

@pytest.fixture
def inproc(tmp_path):
    """같은 프로세스의 게이트웨이 앱(D-118 create_app). lifespan 없이 상태를 직접 갈아 끼운다(상류 클라이언트·체인)."""
    from gateway.audit import AuditLog
    from gateway.auth import Auth
    from gateway.chain import DetectorChain
    from gateway.main import create_app
    from gateway.ratelimit import RateLimiter
    from gateway.settings import Settings
    settings = Settings(auth_off=True)
    app = create_app(settings)
    install(app, settings, DetectorChain([]))
    app.state.auth = Auth(None)
    app.state.audit = AuditLog(tmp_path / "gateway.jsonl")
    app.state.ratelimit = RateLimiter(0)
    yield app
    app.state.audit.close()


@pytest.fixture(scope="module")
def stub_url():
    port = free_port()
    servers = [start(stub_app, port)]
    yield f"http://127.0.0.1:{port}"
    stop(servers)


def _gw(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw", timeout=30)


@pytest.mark.anyio
async def test_v4_pool_exhaustion_is_503_with_retry_after(inproc, stub_url):
    client = httpx.AsyncClient(base_url=stub_url, limits=httpx.Limits(max_connections=1), timeout=httpx.Timeout(10, pool=0.2))
    install(inproc, inproc.state.settings, inproc.state.chain, client)
    try:
        async with _gw(inproc) as gw:
            slow = asyncio.create_task(gw.post(CHAT, json=chat("hi", "stub-slow")))   # 연결 하나를 2초 붙잡는다
            await asyncio.sleep(0.3)
            r = await gw.post(CHAT, json=chat("hi"))
            assert r.status_code == 503 and r.headers["retry-after"] == "1"
            assert r.json()["error"]["code"] == "upstream_busy"
            assert (await slow).status_code == 200
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_v5_full_vault_is_503_and_existing_sessions_survive(inproc, stub_url):
    from gateway.chain import DetectorChain
    from gateway.detectors.pii import PIIDetector
    det = PIIDetector("mask", vault=TokenVault(max_sessions=1))
    live = det.vault.token_for("other-request", "phone", "010-2345-6789")   # 진행 중인 다른 요청이 한 자리를 쓰고 있다
    client = httpx.AsyncClient(base_url=stub_url)
    install(inproc, inproc.state.settings, DetectorChain([det]), client)
    try:
        async with _gw(inproc) as gw:
            r = await gw.post(CHAT, json=chat("제 번호는 010-9876-5432입니다"))
        assert r.status_code == 503 and r.headers["retry-after"] == "1"
        assert r.json()["error"]["code"] == "gateway_busy"
        assert det.vault.restore("other-request", live) == ("010-2345-6789", 1)
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_v6_oversized_upstream_response_is_502(inproc, stub_url, monkeypatch):
    from gateway import relay
    monkeypatch.setattr(relay, "MAX_RESPONSE_BYTES", 100)       # 32MiB 대신 작은 상한으로 같은 길을 본다
    client = httpx.AsyncClient(base_url=stub_url)
    install(inproc, inproc.state.settings, inproc.state.chain, client)
    try:
        async with _gw(inproc) as gw:
            r = await gw.post(CHAT, json=chat("hi"))
            assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_response_too_large"
            ok = await gw.get("/v1/models")
            assert ok.status_code == 502                           # GET /v1/models도 같은 상한
    finally:
        await client.aclose()


# ---------- V7 오프로드 ----------

@pytest.mark.anyio
@pytest.mark.parametrize("size, offloaded", [(100, False), (20_000, True)])
async def test_v7_regex_runs_off_the_event_loop_for_long_text(monkeypatch, size, offloaded):
    from gateway.detectors import injection, pii
    seen: list[int] = []

    def spy(real):
        def wrapped(text):
            seen.append(threading.get_ident())
            return real(text)
        return wrapped

    monkeypatch.setattr(pii, "find_all", spy(pii.find_all))
    monkeypatch.setattr(injection, "match_rules", spy(injection.match_rules))
    body = json.dumps(chat("가" * size)).encode()
    insp = Inspection(request_id="r", method="POST", path=CHAT, headers={}, body=body)
    await pii.PIIDetector("mask").inspect(insp)
    await injection.InjectionRuleDetector(mode="observe").inspect(insp)
    assert len(seen) == 2
    loop_thread = threading.get_ident()
    assert all((t != loop_thread) == offloaded for t in seen)
