"""D-112: 마스킹 범위를 모든 역할로, thinking·reasoning은 손대지 않는다. 번호 M1~M4는 D-112 §4의 표와 같다."""
from __future__ import annotations

import json

import httpx
import pytest

from tests.stub_target import thinking_sig

CHAT, MESSAGES, RESPONSES = "/v1/chat/completions", "/v1/messages", "/v1/responses"
PHONE, EMAIL = "010-2345-6789", "rag@example.com"
RECORD = f"고객 연락처 {PHONE}, 메일 {EMAIL}"          # 검색·도구가 가져온 고객 기록(합성)
ASK = {"role": "user", "content": "이 고객에게 연락할 방법을 요약해 줘"}


def received(stack) -> list[str]:
    return httpx.get(f"{stack.target}/__stub/received").json()["bodies"]


def audit(stack, r: httpx.Response) -> dict:
    (line,) = [x for x in stack.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"]]
    return line


@pytest.fixture(scope="module")
def masked(make_stack):
    return make_stack(GATEWAY_DETECTORS="pii_mask")


# ---------- M1 ----------

CALL = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]}
CASES = {
    "chat-system": (CHAT, {"model": "m", "messages": [{"role": "system", "content": RECORD}, ASK]}),
    "chat-developer": (CHAT, {"model": "m", "messages": [{"role": "developer", "content": [{"type": "text", "text": RECORD}]}, ASK]}),
    "chat-tool": (CHAT, {"model": "m", "messages": [ASK, CALL, {"role": "tool", "tool_call_id": "c1", "content": RECORD}]}),
    "anthropic-system": (MESSAGES, {"model": "m", "max_tokens": 10, "system": RECORD, "messages": [ASK]}),
    "anthropic-system-blocks": (MESSAGES, {"model": "m", "max_tokens": 10, "system": [{"type": "text", "text": RECORD}], "messages": [ASK]}),
    "anthropic-tool-result": (MESSAGES, {"model": "m", "max_tokens": 10, "messages": [
        ASK, {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "lookup", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": RECORD}]}]}]}),
    "anthropic-document": (MESSAGES, {"model": "m", "max_tokens": 10, "messages": [{"role": "user", "content": [
        {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": RECORD}}, {"type": "text", "text": "요약해 줘"}]}]}),
    "responses-instructions": (RESPONSES, {"model": "m", "instructions": RECORD, "input": "요약해 줘"}),
    "responses-function-output": (RESPONSES, {"model": "m", "input": [ASK, {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"},
                                                                   {"type": "function_call_output", "call_id": "c1", "output": RECORD}]}),
}


@pytest.mark.parametrize("case", list(CASES))
def test_m1_values_in_system_document_and_tool_text_do_not_reach_upstream(masked, case):
    path, body = CASES[case]
    r = httpx.post(masked.gateway + path, json=body)
    assert r.status_code == 200, r.text
    raw = received(masked)[-1]
    assert PHONE not in raw and EMAIL not in raw, f"{case}: 원래 값이 상류로 갔다"
    assert audit(masked, r)["transformed"] is True


# ---------- M2 ----------

def test_m2_agent_loop_masks_the_tool_result_and_restores_the_final_answer(masked):
    first = httpx.post(masked.gateway + CHAT, json={"model": "stub-toolcall", "messages": [ASK]}).json()
    call = first["choices"][0]["message"]                       # 모델이 도구를 부른다
    r = httpx.post(masked.gateway + CHAT, json={"model": "stub-agent", "messages": [
        ASK, call, {"role": "tool", "tool_call_id": call["tool_calls"][0]["id"], "content": RECORD}]})
    raw = received(masked)[-1]
    assert PHONE not in raw and EMAIL not in raw                # 도구 결과는 가짜 값으로 갔고
    assert r.json()["choices"][0]["message"]["content"] == f"[stub] {RECORD}"   # 최종 답은 원래 값으로 돌아온다


# ---------- M3 ----------

USER1 = {"role": "user", "content": f"제 번호는 {PHONE}입니다"}


def test_m3_thinking_block_bytes_are_untouched_and_verify_on_the_next_turn(masked):
    r1 = httpx.post(masked.gateway + MESSAGES, json={"model": "stub-thinking", "max_tokens": 100, "messages": [USER1]})
    content = r1.json()["content"]
    thinking, text = content[0], content[1]
    assert thinking["type"] == "thinking" and thinking["signature"] == thinking_sig(thinking["thinking"])
    assert PHONE not in thinking["thinking"], "thinking을 복원했다 — 다음 턴에 원래 값이 thinking에 담겨 상류로 간다"
    assert PHONE in text["text"]
    assert audit(masked, r1)["response_detectors"][0]["residual_tokens"] == 0   # thinking 속 가짜 값은 잔여로 세지 않는다
    r2 = httpx.post(masked.gateway + MESSAGES, json={"model": "stub-thinking", "max_tokens": 100, "messages": [
        USER1, {"role": "assistant", "content": content}, {"role": "user", "content": "다시 말해 줘"}]})
    seen = r2.json()["gateway_test"]
    assert seen["thinking_seen"] == 1 and seen["thinking_ok"] is True and seen["thinking_raw_seen"] is False


def _events(gateway: str, path: str, body: dict) -> list[dict]:
    with httpx.stream("POST", gateway + path, json=body, timeout=30) as r:
        assert r.status_code == 200
        return [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ") and x != "data: [DONE]"]


def test_m3_streamed_thinking_deltas_and_signature_are_untouched(masked):
    events = _events(masked.gateway, MESSAGES, {"model": "stub-stream-thinking", "max_tokens": 100, "stream": True, "messages": [USER1]})
    deltas = [e["delta"] for e in events if e.get("type") == "content_block_delta"]
    thinking = "".join(d["thinking"] for d in deltas if d["type"] == "thinking_delta")
    (sig,) = [d["signature"] for d in deltas if d["type"] == "signature_delta"]
    text = "".join(d["text"] for d in deltas if d["type"] == "text_delta")
    assert sig == thinking_sig(thinking) and PHONE not in thinking and PHONE in text


def test_m3_responses_reasoning_summary_is_untouched(masked):
    r = httpx.post(masked.gateway + RESPONSES, json={"model": "stub-reasoning", "input": USER1["content"]})
    out = r.json()["output"]
    assert out[0]["type"] == "reasoning" and PHONE not in out[0]["summary"][0]["text"]
    assert PHONE in out[1]["content"][0]["text"]
    assert audit(masked, r)["response_detectors"][0]["residual_tokens"] == 0
    events = _events(masked.gateway, RESPONSES, {"model": "stub-stream-reasoning", "input": USER1["content"], "stream": True})
    (done,) = [e for e in events if e.get("type") == "response.completed"]
    reasoning, message = done["response"]["output"][0], done["response"]["output"][1]
    assert PHONE not in reasoning["summary"][0]["text"] and PHONE in message["content"][0]["text"]


# ---------- M4 ----------

def test_m4_roles_can_be_narrowed_back_to_the_old_behaviour(make_stack):
    s = make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_ROLES="user,assistant")
    httpx.post(s.gateway + CHAT, json={"model": "m", "messages": [{"role": "system", "content": RECORD}, USER1]})
    sent = json.loads(received(s)[-1])["messages"]
    assert PHONE in sent[0]["content"] and EMAIL in sent[0]["content"]   # system은 평문(옛 동작)
    assert PHONE not in sent[1]["content"]


def test_m4_unknown_role_does_not_boot(make_stack):
    with pytest.raises(RuntimeError, match="기동 실패"):
        make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_ROLES="user,boss")
