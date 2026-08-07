"""4-C 통합 검증: 체인이 실제 게이트웨이에 배선됐을 때의 동작."""
from __future__ import annotations

import httpx
import pytest

PATH_ = "/api/v1/workspace/demo-slug/chat"
HDR = {"Authorization": "Bearer k", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def noop_stack(make_stack):
    return make_stack(GATEWAY_DETECTORS="noop")


@pytest.fixture(scope="module")
def rules_stack(make_stack):
    return make_stack("tests.chain_app:app", GATEWAY_DETECTORS="test_mask,test_block")


def test_noop_chain_does_not_change_response(noop_stack):
    """4-C의 핵심. 검사기를 꽂아도 4-A의 투명성이 유지된다."""
    body = {"message": "평범한 질문입니다", "mode": "query"}
    direct = httpx.post(f"{noop_stack.target}{PATH_}", json=body, headers=HDR)
    proxied = httpx.post(f"{noop_stack.gateway}{PATH_}", json=body, headers=HDR)
    assert direct.json() == proxied.json()


def test_chain_steps_are_logged(noop_stack):
    """EVAL 4절: 검사기별 소요 시간이 감사 로그에 남는다."""
    httpx.post(f"{noop_stack.gateway}{PATH_}", json={"message": "hi"}, headers=HDR)
    rec = noop_stack.log_lines()[-1]
    assert rec["chain_ms"] is not None
    assert [d["detector"] for d in rec["detectors"]] == ["noop"]
    assert rec["detectors"][0]["action"] == "allow"
    assert rec["blocked"] is False and rec["blocked_by"] is None


def test_transform_reaches_target_masked(rules_stack):
    """마스킹된 본문이 타겟에 전달된다. 원문은 타겟이 보지 못한다."""
    r = httpx.post(f"{rules_stack.gateway}{PATH_}",
                   json={"message": "내 값은 SECRET 이다", "mode": "query"}, headers=HDR)
    echo = r.json()["echo"]
    assert echo["body"]["message"] == "내 값은 [MASKED] 이다"
    assert "SECRET" not in r.text
    rec = rules_stack.log_lines()[-1]
    assert rec["transformed"] is True
    assert rec["blocked"] is False


def test_block_returns_200_with_target_schema(rules_stack):
    """차단도 200 + textResponse. garak의 total_evaluated를 보존해 EVAL 5.2를 지킨다."""
    r = httpx.post(f"{rules_stack.gateway}{PATH_}",
                   json={"message": "BLOCKME 지금 당장", "mode": "query"}, headers=HDR)
    assert r.status_code == 200
    payload = r.json()
    assert payload["gateway_blocked"] is True
    assert isinstance(payload["textResponse"], str) and payload["textResponse"]
    assert "echo" not in payload, "차단됐는데 타겟까지 요청이 갔다"


def test_block_does_not_leak_rule_to_attacker(rules_stack):
    """차단 사유는 응답에 넣지 않는다. 사유는 감사 로그에만 있다."""
    r = httpx.post(f"{rules_stack.gateway}{PATH_}",
                   json={"message": "BLOCKME", "mode": "query"}, headers=HDR)
    assert "test_block" not in r.text and "차단 규칙" not in r.text
    rec = rules_stack.log_lines()[-1]
    assert rec["blocked"] is True and rec["blocked_by"] == "test_block"
    assert any(d.get("reason") == "테스트용 차단 규칙 일치" for d in rec["detectors"])


def test_blocked_request_skips_target_call(rules_stack):
    """차단 시 타겟을 호출하지 않으므로 upstream_ms가 없다."""
    httpx.post(f"{rules_stack.gateway}{PATH_}", json={"message": "BLOCKME"}, headers=HDR)
    rec = rules_stack.log_lines()[-1]
    assert rec["upstream_ms"] is None
    assert rec["gateway_ms"] == rec["total_ms"]


def test_unknown_detector_name_fails_fast(make_stack):
    """오타 난 검사기 이름으로 조용히 무방비 가동되는 일이 없어야 한다."""
    import subprocess
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        make_stack(GATEWAY_DETECTORS="typo_detector")
