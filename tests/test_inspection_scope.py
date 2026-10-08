"""D-095 특성화: 현행(A) 인젝션 검사 범위 — 이력의 user 턴까지 본다. 합성 OpenAI 본문, LLM 없음.

현행 동작의 기록이다. 검사 범위를 바꾸는 브랜치(D-095 §3)에서는 두 번째·세 번째 테스트의 기대가 의도적으로 바뀐다.
B-103은 정상셋 100문항 중 룰이 막는 유일한 정상 문항이다(test_injection.test_only_b103_fires_across_full_benign_set).
공격 문구는 쓰지 않는다(원칙 2).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

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
