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


# ---------- 4-E: 마스킹이 실제 게이트웨이에 배선됐을 때 ----------

@pytest.fixture(scope="module")
def mask_stack(make_stack):
    return make_stack(GATEWAY_DETECTORS="pii_mask")


def test_target_never_sees_the_original_pii(mask_stack):
    """SCOPE 2절의 위협 그 자체. 타겟과 그 뒤의 LLM이 원문을 보면 안 된다."""
    rrn, phone = "900101-1234563", "010-2345-6789"
    r = httpx.post(f"{mask_stack.gateway}{PATH_}", headers=HDR, json={
        "message": f"주민등록번호 {rrn}이고 연락처 {phone}입니다. 병가는 며칠인가요?",
        "mode": "query", "sessionId": "eval-mask-1"})
    echo_msg = r.json()["echo"]["body"]["message"]
    assert rrn not in echo_msg and phone not in echo_msg
    assert "[PII:rrn:1]" in echo_msg and "[PII:phone:2]" in echo_msg


def test_masking_is_logged_without_the_value(mask_stack):
    httpx.post(f"{mask_stack.gateway}{PATH_}", headers=HDR, json={
        "message": "카드 4111-1111-1111-1111로 결제했습니다", "mode": "query",
        "sessionId": "eval-mask-2"})
    raw = mask_stack.log_path.read_text(encoding="utf-8")
    assert "4111-1111-1111-1111" not in raw
    rec = mask_stack.log_lines()[-1]
    assert rec["transformed"] is True and rec["blocked"] is False
    step = rec["detectors"][0]
    assert step["action"] == "transform" and step["pii"] == {"card": 1}


def test_normal_question_is_untouched(mask_stack):
    """PII가 없는 정상 질문은 4-A와 완전히 같아야 한다. FPR을 지키는 지점."""
    q = {"message": "표준 근무시간은 몇 시부터인가요?", "mode": "query", "sessionId": "eval-mask-3"}
    direct = httpx.post(f"{mask_stack.target}{PATH_}", json=q, headers=HDR)
    proxied = httpx.post(f"{mask_stack.gateway}{PATH_}", json=q, headers=HDR)
    assert direct.json() == proxied.json()
    assert mask_stack.log_lines()[-1]["transformed"] is False
