"""D-131(PLAN 21단계): 공개 데모 — 공개 모드의 스텁 고정·본문 상한·레이트리밋·방문자 분리·로그 상한, 데모 이미지와 배포 견본의 구조."""
from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from gateway.ratelimit import RateLimiter
from tests.conftest import free_port, serve, start, stop

ROOT = Path(__file__).resolve().parents[1]
VISITOR = "x-demo-visitor"      # 시험용 방문자 헤더 — 배포에서는 프록시가 채우는 헤더(Fly-Client-IP)다
PER_VISITOR = 6
LOG_MAX = 3000


def body(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


@pytest.fixture(scope="module")
def public():
    """실제 서버(서브프로세스) — 동시 요청과 한도를 본다. 실제 공급자 설정을 일부러 넣어 무시되는지 본다."""
    port = free_port()
    env = {"WEB_PUBLIC": "1", "WEB_ON_TARGET": "https://api.anthropic.com", "WEB_ON_MODEL": "claude-opus-5-5", "ANTHROPIC_API_KEY": "not-a-real-key",
           "WEB_CLIENT_IP_HEADER": VISITOR, "WEB_RATE_PER_MINUTE": str(PER_VISITOR), "WEB_RATE_TOTAL_PER_MINUTE": "1000"}
    p = serve("web.app:app", port, env, probe="/api/scenes")    # scenes는 한도를 쓰지 않는다
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        p.terminate()
        p.wait(10)


@pytest.fixture(scope="module")
def inproc():
    """같은 프로세스의 스레드에서 띄운 앱 — 스텁 주소와 로그 파일을 직접 본다."""
    from web.app import app
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("WEB_PUBLIC", "1")
        mp.setenv("WEB_LOG_MAX_BYTES", str(LOG_MAX))
        mp.setenv("WEB_RATE_PER_MINUTE", "1000")
        mp.delenv("WEB_CLIENT_IP_HEADER", raising=False)
        port = free_port()
        running = start(app, port)
        try:
            yield f"http://127.0.0.1:{port}", app
        finally:
            stop([running])


# ---------- P1 상류는 스텁 고정 ----------

def test_p1_public_mode_pins_both_arms_to_the_stub(public, monkeypatch):
    info = httpx.get(public + "/api/info", headers={VISITOR: "p1"}).json()
    assert info["public"] is True and info["real"] is False and info["model"] == "stub-model"
    assert info["on"]["upstream"] == info["off"]["upstream"] == "스텁 모델"
    assert not any(s["disabled"] for s in httpx.get(public + "/api/scenes").json())       # 인젝션 장면도 켜져 있다 — 스텁이라 보내도 된다
    out = httpx.post(public + "/api/chat", json=body("제 번호는 010-2345-6789입니다"), headers={VISITOR: "p1"}).json()
    assert out["off"]["upstream"][-1]["content"] == "제 번호는 010-2345-6789입니다"            # 상류가 받은 것이 보인다 = 스텁이다
    assert "010-2345-6789" not in out["on"]["upstream"][-1]["content"] and "010-2345-6789" in out["on"]["answer"]

    from web.app import arm_target
    monkeypatch.setenv("WEB_ON_TARGET", "https://api.anthropic.com")
    assert arm_target("on", "http://stub") == "https://api.anthropic.com"                # 로컬 모드는 예전 그대로
    monkeypatch.setenv("WEB_PUBLIC", "1")
    assert arm_target("on", "http://stub") == arm_target("off", "http://stub") == "http://stub"


# ---------- P2 본문 상한 ----------

def test_p1_every_preset_scene_reaches_both_arms(public):
    """공개 화면의 장면 여섯이 모두 두 팔의 결과를 낸다 — '너무 큰 본문'(장면 6)은 웹 층이 아니라 게이트웨이 팔이 413으로 끊어야 한다(리뷰)."""
    scenes = httpx.get(public + "/api/scenes").json()
    assert [s["id"] for s in scenes] == [1, 2, 3, 4, 5, 6]
    for s in scenes:
        r = httpx.post(public + "/api/chat", json={"messages": s["messages"]}, headers={VISITOR: f"scene-{s['id']}"}, timeout=30)
        assert r.status_code == 200, (s["id"], r.status_code, r.text[:120])
        out = r.json()
        assert {out["off"]["status"], out["on"]["status"]} == ({413} if s["id"] == 6 else {200}), s["id"]
    for path in ("/docs", "/redoc", "/openapi.json"):                                     # 문서 경로는 열지 않는다
        assert httpx.get(public + path).status_code == 404, path


def test_p2_body_over_the_cap_is_413(public):
    from web.app import PUBLIC_BODY
    url, h = public + "/api/chat", {VISITOR: "p2", "content-type": "application/json"}
    room = PUBLIC_BODY - len(json.dumps(body("")).encode())
    exact, over = (json.dumps(body("a" * n)).encode() for n in (room, room + 1))
    assert (len(exact), len(over)) == (8192, 8193)
    assert httpx.post(url, content=exact, headers=h).status_code == 200                 # 웹 층은 통과 — 게이트웨이 팔(상한 4,096)이 413을 낸다
    assert httpx.post(url, content=over, headers=h).status_code == 413
    assert httpx.post(url, content=iter([over[:2000], over[2000:]]), headers=h).status_code == 413   # Content-Length 없이(chunked) — 읽은 양으로 끊는다
    assert httpx.post(url, content=b"[" * 4000, headers=h).status_code == 400            # 깊게 중첩된 JSON도 500이 아니다
    assert httpx.post(url, content=b"\xff\xfe", headers=h).status_code == 400
    assert httpx.post(url, content=b'{"messages":[{"role":"user","content":"\\ud800"}]}', headers=h).status_code == 400    # 짝 없는 서로게이트 — 상류로 보낼 때 터지지 않게 400


def test_p2_slow_body_is_cut_off(inproc, monkeypatch):
    """본문을 한 바이트씩 흘려 연결을 쥐고 있지 못한다 — 기한 안에 다 오지 않으면 408."""
    base, _ = inproc
    import web.app as web_app
    monkeypatch.setattr(web_app, "BODY_DEADLINE", 0.3)
    host, port = base.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as s:
        s.sendall(b"POST /api/chat HTTP/1.1\r\nHost: demo\r\nContent-Type: application/json\r\nContent-Length: 60\r\n\r\n{")
        started = time.monotonic()
        head = s.recv(200)
    assert head.startswith(b"HTTP/1.1 408") and time.monotonic() - started < 5


# ---------- P3 레이트리밋 ----------

def test_p3_each_visitor_has_its_own_limit(public):
    def hit(visitor: str) -> httpx.Response:
        return httpx.post(public + "/api/chat", json=body("연차는 며칠인가요?"), headers={VISITOR: visitor})
    assert [hit("p3-a").status_code for _ in range(PER_VISITOR + 2)] == [200] * PER_VISITOR + [429, 429]
    refused = hit("p3-a")
    assert refused.status_code == 429 and 1 <= int(refused.headers["retry-after"]) <= 60
    assert httpx.get(public + "/api/info", headers={VISITOR: "p3-a"}).status_code == 429   # 게이트웨이를 부르는 info도 같은 한도다
    assert hit("p3-b").status_code == 200                                                 # 다른 방문자는 따로 센다


def _request(state: SimpleNamespace, headers: dict[str, str], peer: str = "10.0.0.1") -> Request:
    return Request({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()], "client": (peer, 1), "app": SimpleNamespace(state=state)})


def test_p3_total_limit_and_visitor_key(monkeypatch):
    from web.app import _limit
    monkeypatch.setenv("WEB_CLIENT_IP_HEADER", VISITOR)
    state = SimpleNamespace(per_visitor=RateLimiter(100), total=RateLimiter(3))
    for i in range(3):
        _limit(_request(state, {VISITOR: f"v{i}"}))
    with pytest.raises(HTTPException) as refused:                                         # 방문자 주소를 바꿔도 전체 상한에 걸린다
        _limit(_request(state, {VISITOR: "v-new"}))
    assert refused.value.status_code == 429 and int(refused.value.headers["Retry-After"]) >= 1

    monkeypatch.delenv("WEB_CLIENT_IP_HEADER")                                            # 헤더를 정하지 않으면 소켓 주소 — X-Forwarded-For는 보지 않는다
    state = SimpleNamespace(per_visitor=RateLimiter(1), total=RateLimiter(100))
    _limit(_request(state, {"x-forwarded-for": "1.1.1.1", VISITOR: "a"}))
    with pytest.raises(HTTPException):
        _limit(_request(state, {"x-forwarded-for": "2.2.2.2", VISITOR: "b"}))
    _limit(_request(state, {}, peer="10.0.0.2"))

    from web.app import _visitor
    monkeypatch.setenv("WEB_CLIENT_IP_HEADER", VISITOR)
    key = lambda value: _visitor(_request(state, {VISITOR: value}))      # noqa: E731
    assert key("2001:db8:1:2:aaaa::1") == key("2001:db8:1:2:bbbb::9") != key("2001:db8:1:3::1")      # IPv6는 /64로 묶는다 — 주소를 돌려 한도를 피하지 못한다
    assert key("203.0.113.7") == "203.0.113.7" != key("203.0.113.8") and key(" 203.0.113.7 ") == "203.0.113.7"
    assert len(key("x" * 500)) == 64                                                               # 주소가 아닌 값은 잘라 키로
    two = Request({"type": "http", "headers": [(VISITOR.encode(), b"1.1.1.1"), (VISITOR.encode(), b"203.0.113.9")], "client": ("10.0.0.1", 1), "app": SimpleNamespace(state=state)})
    assert _visitor(two) == "203.0.113.9"                                                          # 같은 헤더가 둘이면 프록시가 붙인 마지막 값


# ---------- P4 방문자 분리 ----------

def test_p4_concurrent_visitors_see_only_their_own_text(public):
    """잠금이 없으면 '상류가 받은 것'에 남의 문장이 보인다(D-131 §1 재현: 24팔 중 19팔)."""
    def one(i: int) -> list[bool]:
        text = f"방문자{i:02d}의 메모입니다"
        h = {VISITOR: f"p4-{i}"}
        if i % 2:
            out = httpx.post(public + "/api/chat", json=body(text), headers=h, timeout=30).json()
        else:       # 스트리밍 — 줄마다 JSON, 팔마다 결과 한 줄
            rows = [json.loads(line) for line in httpx.post(public + "/api/chat?stream=1", json=body(text), headers=h, timeout=30).text.splitlines()]
            assert "".join(r["delta"] for r in rows if "delta" in r).endswith(text)       # 스텁이 되돌려준 답이 조각으로 왔다
            out = {r["arm"]: r for r in rows if "upstream" in r}
        return [out[arm]["upstream"][-1]["content"] == text for arm in ("off", "on")]
    with ThreadPoolExecutor(12) as pool:
        assert list(pool.map(one, range(12))) == [[True, True]] * 12


def test_p4_stub_keeps_nothing_after_the_request(inproc):
    base, app = inproc
    out = httpx.post(base + "/api/chat", json=body("제 번호는 010-2345-6789입니다")).json()
    assert out["off"]["upstream"][-1]["content"] == "제 번호는 010-2345-6789입니다"
    for arm in app.state.arms.values():                                                   # '없음' 팔의 스텁은 원문을 받았다 — 요청이 끝나면 없다
        assert httpx.get(arm["stub"] + "/__stub/received").json()["bodies"] == []


def test_p4_deadline_is_503_and_the_lock_is_released(inproc, monkeypatch):
    base, _ = inproc
    import web.app as web_app

    async def slow(request, arm, messages):
        await asyncio.sleep(5)

    monkeypatch.setattr(web_app, "_run", slow)
    monkeypatch.setattr(web_app, "PUBLIC_DEADLINE", 0.2)
    refused = httpx.post(base + "/api/chat", json=body("안녕하세요"))
    assert refused.status_code == 503 and refused.headers["retry-after"] == "5"
    monkeypatch.undo()
    assert httpx.post(base + "/api/chat", json=body("안녕하세요")).status_code == 200            # 잠금을 쥔 채로 끝나지 않았다


# ---------- P5 감사 로그 상한 ----------

def test_p5_audit_log_stays_bounded_and_readable(inproc):
    base, app = inproc
    sizes = []
    for i in range(30):
        out = httpx.post(base + "/api/chat", json=body(f"연차는 며칠인가요? {i}")).json()
        assert out["on"]["audit"]["status"] == out["off"]["audit"]["status"] == 200       # 비운 뒤에 붙은 줄도 읽힌다
        sizes.append(max(a["log"].stat().st_size for a in app.state.arms.values()))
    assert max(sizes) <= LOG_MAX                                                          # 넘으면 그 요청 끝에 비운다
    assert any(later < earlier for earlier, later in zip(sizes, sizes[1:]))               # 실제로 비워졌다(30건이면 상한을 여러 번 넘는다)


# ---------- P7 데모 이미지·배포 견본 ----------

def test_p7_demo_image_and_fly_config():
    docker = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM (\S+)$", (ROOT / "gateway" / "Dockerfile").read_text(encoding="utf-8"), re.M)[1]
    assert re.search(r"^FROM (\S+)$", docker, re.M)[1] == base and "@sha256:" in base     # 게이트웨이와 같은 고정 베이스
    assert re.search(r"^USER 10001$", docker, re.M) and re.search(r"^\s+WEB_PUBLIC=1$", docker, re.M)
    port = re.search(r"^EXPOSE (\d+)$", docker, re.M)[1]
    assert f'"--port", "{port}"' in docker and "--no-access-log" in docker

    ignore = [line for line in (ROOT / "web" / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert ignore[0] == "*"                                                               # 전부 빼고 쓰는 것만 넣는다(.env·models·eval이 문맥에 없다)
    allow = {line[1:] for line in ignore if line.startswith("!")}
    sources = [src.rstrip("/") for line in re.findall(r"^COPY (.+)$", docker, re.M) for src in line.split()[:-1]]
    assert sources and all((ROOT / src).exists() and (src in allow or src.split("/")[0] in allow) for src in sources), sources
    assert not allow & {".env", "tests", "models", "eval", "docs", ".git"}

    fly = tomllib.loads((ROOT / "deploy" / "demo" / "fly.toml").read_text(encoding="utf-8"))
    assert fly["http_service"]["internal_port"] == int(port) and fly["http_service"]["force_https"] is True
    assert fly["env"] == {"WEB_CLIENT_IP_HEADER": "Fly-Client-IP"}                        # 공개 모드는 이미지가 켠다 — 견본이 끄지 않는다

    # 이미지가 싣는 모듈은 pytest 없이 import된다(이미지에 테스트 러너를 넣지 않는다)
    probe = "import sys; sys.modules['pytest'] = None; import tests.procs, tests.stub_target, web.app"
    done = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
