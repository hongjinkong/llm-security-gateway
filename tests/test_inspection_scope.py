"""인젝션 검사 범위 두 가지 — 합성 OpenAI 본문, 스텁 상류, LLM 없음.

(A) `injection_rule`: 이력의 user·tool 턴까지 전부 본다. D-095 특성화 테스트 세 개가 그 동작(세션 오염)을 기록한다.
(C) `injection_rule_turn`(D-099): 막을지는 이번 턴만 보고, 이력의 걸린 메시지는 가려서 보낸다.
두 검사기는 함께 남는다 — 같은 코드 지문에서 두 범위를 나란히 재기 위해서다(D-100).
B-103은 정상셋 100문항 중 룰이 막는 유일한 정상 문항이다(test_injection.test_only_b103_fires_across_full_benign_set).
공격 문구는 쓰지 않는다(원칙 2).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from gateway.detectors.base import Action, Inspection
from gateway.detectors.injection import REDACTED_TURN, InjectionRuleDetector

PATH = "/v1/chat/completions"
HEADERS = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
BENIGN = Path(__file__).resolve().parents[1] / "eval" / "benign" / "all100.jsonl"
BLOCKED = "요청이 보안 정책에 의해 차단되었습니다."   # 게이트웨이 기본 차단 문구. assistant 턴은 검사 대상이 아니다
ASK = "연차는 며칠인가요?"
ANSWER = "연차는 15일입니다."


def b103() -> str:
    rows = [json.loads(x) for x in BENIGN.read_text(encoding="utf-8").split("\n") if x.strip()]
    return next(r["q"] for r in rows if r["id"] == "B-103")


@pytest.fixture(scope="module")
def secured(make_stack):
    return make_stack(GATEWAY_DETECTORS="injection_rule,pii_mask")


def send(stack, messages: list[dict]) -> dict:
    r = httpx.post(f"{stack.gateway}{PATH}", headers=HEADERS, json={"model": "stub-model", "messages": messages})
    assert r.status_code == 200
    return r.json()


def test_정상_이력_뒤_정상_질문은_상류로_간다(secured):
    payload = send(secured, [{"role": "user", "content": ASK}, {"role": "assistant", "content": ANSWER},
                             {"role": "user", "content": ASK}])
    assert "gateway_blocked" not in payload
    assert "gateway_test" in payload           # 스텁 상류가 답했다


def test_이력의_막힌_정상_질문이_다음_정상_질문을_막는다(secured):
    """세션 오염(D-093 §3 가설 1). 마지막 질문은 위 테스트와 같고, 다른 것은 앞 턴의 B-103뿐이다."""
    payload = send(secured, [{"role": "user", "content": b103()}, {"role": "assistant", "content": BLOCKED},
                             {"role": "user", "content": ASK}])
    assert payload["gateway_blocked"] is True
    assert "gateway_test" not in payload       # 상류로 가지 않았다


def test_게이트웨이에는_이력_기한이_없다(secured):
    """정상 대화 19쌍 뒤에 있어도 막는다. 오염이 언제 끝나는지는 클라이언트 이력(AnythingLLM 20개·압축)이 정한다."""
    messages = [{"role": "user", "content": b103()}, {"role": "assistant", "content": BLOCKED}]
    for _ in range(19):
        messages += [{"role": "user", "content": ASK}, {"role": "assistant", "content": ANSWER}]
    messages.append({"role": "user", "content": ASK})
    assert send(secured, messages)["gateway_blocked"] is True


# ---------------------------------------------------------------------------------------------
# D-099: (C) `injection_rule_turn` — 막을지는 이번 턴만 보고, 이력의 걸린 메시지는 가려서 보낸다.
# 위 (A) 세 테스트는 `injection_rule`의 기록으로 그대로 둔다. 같은 본문이 (C)에서 어떻게 달라지는지가 아래다.

@pytest.fixture(scope="module")
def turn(make_stack):
    return make_stack(GATEWAY_DETECTORS="injection_rule_turn,pii_mask")


def upstream_messages(stack) -> list[dict]:
    """스텁 상류가 실제로 받은 마지막 본문의 messages."""
    bodies = httpx.get(f"{stack.target}/__stub/received").json()["bodies"]
    return json.loads(bodies[-1])["messages"]


def audit_of(stack, request_id: str) -> dict:
    return next(x for x in stack.log_lines() if x["request_id"] == request_id)


def test_turn_이력의_막힌_정상_질문은_가려지고_다음_질문은_상류로_간다(turn):
    """(A)의 두 번째 테스트와 같은 본문. (C)에서는 막지 않고 그 턴만 가린다."""
    r = httpx.post(f"{turn.gateway}{PATH}", headers=HEADERS, json={"model": "stub-model", "messages": [
        {"role": "user", "content": b103()}, {"role": "assistant", "content": BLOCKED},
        {"role": "user", "content": ASK}]})
    assert r.status_code == 200 and "gateway_blocked" not in r.json()
    sent = upstream_messages(turn)
    assert [m["content"] for m in sent] == [REDACTED_TURN, BLOCKED, ASK]
    line = audit_of(turn, r.headers["X-Gateway-Request-Id"])
    assert line["blocked"] is False and line["transformed"] is True
    step = next(s for s in line["detectors"] if s["detector"] == "injection_rule_turn")
    assert step["action"] == "transform" and step["masked_turns"] == 1


def test_turn_이력_기한_없이_막던_요청도_상류로_간다(turn):
    """(A)의 세 번째 테스트와 같은 본문 — 세션 오염이 없다."""
    messages = [{"role": "user", "content": b103()}, {"role": "assistant", "content": BLOCKED}]
    for _ in range(19):
        messages += [{"role": "user", "content": ASK}, {"role": "assistant", "content": ANSWER}]
    messages.append({"role": "user", "content": ASK})
    assert "gateway_blocked" not in send(turn, messages)
    assert upstream_messages(turn)[0]["content"] == REDACTED_TURN


def test_turn_이번_턴이_걸리면_막는다(turn):
    payload = send(turn, [{"role": "user", "content": ASK}, {"role": "assistant", "content": ANSWER},
                          {"role": "user", "content": b103()}])
    assert payload["gateway_blocked"] is True


def test_turn_마지막_user_뒤의_tool은_이번_턴이다(turn):
    """간접 인젝션 자리. 마지막 user 뒤에 온 tool 메시지가 걸리면 막는다."""
    payload = send(turn, [{"role": "user", "content": "문서를 요약해줘"},
                          {"role": "tool", "content": b103()}])
    assert payload["gateway_blocked"] is True


def test_turn_이력의_tool은_가린다(turn):
    payload = send(turn, [{"role": "user", "content": "문서를 요약해줘"}, {"role": "tool", "content": b103()},
                          {"role": "assistant", "content": ANSWER}, {"role": "user", "content": ASK}])
    assert "gateway_blocked" not in payload
    assert upstream_messages(turn)[1]["content"] == REDACTED_TURN


@pytest.mark.anyio
async def test_turn_content_parts는_텍스트만_가린다():
    image ={"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
    body = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": [{"type": "text", "text": b103()}, image]},
        {"role": "assistant", "content": BLOCKED},
        {"role": "user", "content": ASK}]}, ensure_ascii=False).encode()
    v = await InjectionRuleDetector(scope="turn").inspect(
        Inspection(request_id="r", method="POST", path=PATH, headers={}, body=body))
    assert v.action is Action.TRANSFORM and v.detector == "injection_rule_turn"
    first = json.loads(v.body)["messages"][0]["content"]
    assert first == [{"type": "text", "text": REDACTED_TURN}, image]


def test_scope_값이_틀리면_만들지_않는다():
    with pytest.raises(ValueError):
        InjectionRuleDetector(scope="last")


@pytest.fixture
def anyio_backend():
    return "asyncio"
