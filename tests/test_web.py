"""D-104: 데모 웹 — 두 팔(게이트웨이 없음/있음)의 비교 응답 계약."""
from __future__ import annotations

import httpx
import pytest

from tests.conftest import free_port, serve
from web.app import arm_target


@pytest.fixture(scope="module")
def web():
    port = free_port()
    p = serve("web.app:app", port, probe="/api/info")     # lifespan이 스텁 둘과 게이트웨이 둘을 띄운 뒤에야 응답한다
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        p.terminate()
        p.wait(10)


def chat(web: str, scene_id: int) -> dict:
    scene = next(s for s in httpx.get(f"{web}/api/scenes").json() if s["id"] == scene_id)
    return httpx.post(f"{web}/api/chat", json={"messages": scene["messages"]}, timeout=30).json()


def test_info_and_scenes(web):
    info = httpx.get(f"{web}/api/info").json()
    assert info["off"]["detectors"] == [] and info["on"]["detectors"] == ["injection_rule_turn", "pii_mask"]
    assert info["real"] is False and info["on"]["code"] == info["off"]["code"]
    assert [s["id"] for s in httpx.get(f"{web}/api/scenes").json()] == [1, 2, 3, 4, 5, 6]
    assert "게이트웨이" in httpx.get(f"{web}/").text


def test_pii_scene_masks_upstream_and_restores_answer(web):
    out = chat(web, 1)
    assert "010-2345-6789" in out["off"]["upstream"][0]["content"]            # 없음: 원문이 상류로 간다
    assert "[PII:phone:1]" in out["on"]["upstream"][0]["content"]            # 있음: 토큰만 간다
    assert "010-2345-6789" not in out["on"]["upstream"][0]["content"]
    assert "010-2345-6789" in out["on"]["answer"]                            # 사용자는 원래 값을 돌려받는다
    assert out["on"]["audit"]["transformed"] and out["on"]["audit"]["response_detectors"][0]["restored"] == 2


def test_injection_scene_blocks_only_with_gateway(web):
    out = chat(web, 4)
    assert out["off"]["status"] == 200 and not out["off"]["blocked"] and out["off"]["upstream"]
    assert out["on"]["blocked"] and out["on"]["upstream"] is None and out["on"]["audit"]["blocked"]
    masked = chat(web, 5)
    assert masked["on"]["status"] == 200 and not masked["on"]["blocked"]
    assert masked["on"]["upstream"][0]["content"] == "[보안 정책에 의해 가려진 이전 메시지]"
    assert chat(web, 6)["on"]["status"] == 413


def test_bad_input_is_400(web):
    assert httpx.post(f"{web}/api/chat", json={"messages": []}).status_code == 400
    assert httpx.post(f"{web}/api/chat", json={"messages": [{"role": "system", "content": "x"}]}).status_code == 400


def test_off_arm_never_uses_a_real_target(monkeypatch):
    monkeypatch.setenv("WEB_ON_TARGET", "https://api.anthropic.com")
    assert arm_target("off", "http://127.0.0.1:1") == "http://127.0.0.1:1"
    assert arm_target("on", "http://127.0.0.1:1") == "https://api.anthropic.com"
