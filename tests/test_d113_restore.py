"""D-113: 응답 필드별 복원, 복원 가시화, 안전한 가짜 이메일. 번호 F1~F5는 D-113 §4의 표와 같다."""
from __future__ import annotations

import json

import httpx
import pytest

from gateway.detectors.patterns import find_all
from gateway.vault import TokenVault
from tests.conftest import ADMIN

CHAT, MESSAGES, RESPONSES = "/v1/chat/completions", "/v1/messages", "/v1/responses"
PHONE, EMAIL = "010-2345-6789", "j.hong@hanbit-tech.example"
PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nhkiG9w0BAQEFAASCBKcwggSjAgEAAoIB\n-----END PRIVATE KEY-----"
# 줄바꿈 구분자 전화 — 원래 값에 개행이 있어 안쪽 JSON 이스케이프 없이 끼우면 인자가 깨진다(대체값은 빈칸 구분)
NL_PHONE = "010\n2345\n6789"


@pytest.fixture(scope="module")
def masked(make_stack):
    return make_stack(GATEWAY_DETECTORS="pii_mask")


def received(stack) -> list[str]:
    return httpx.get(f"{stack.target}/__stub/received").json()["bodies"]


def audit(stack, r: httpx.Response) -> dict:
    (line,) = [x for x in stack.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"]]
    return line


def chat(content: str, model: str, **extra) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": content}], **extra}


# ---------- F1 도구 인자 ----------

@pytest.mark.parametrize("value", [PEM, NL_PHONE], ids=["pem", "newline-phone"])
def test_f1_chat_tool_arguments_with_newlines_stay_valid_json(masked, value):
    r = httpx.post(masked.gateway + CHAT, json=chat(f"키 {value}", "stub-toolcall"))
    args = r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args) == {"to": f"키 {value}"}                    # 안쪽 JSON이 깨지지 않고 원래 값과 같다
    assert "MIIEvQIBADANBgkq" not in received(masked)[-1] and "2345\\n6789" not in received(masked)[-1]


def test_f1_responses_function_call_arguments_with_pem_stay_valid_json(masked):
    r = httpx.post(masked.gateway + RESPONSES, json={"model": "stub-tool", "input": f"키 {PEM}"})
    (call,) = [o for o in r.json()["output"] if o["type"] == "function_call"]
    assert json.loads(call["arguments"]) == {"to": f"키 {PEM}", "note": f"메모 키 {PEM}"}


def test_f1_streamed_tool_arguments_with_pem_stay_valid_json(masked):
    with httpx.stream("POST", masked.gateway + CHAT, json=chat(f"키 {PEM}", "stub-stream-tool", stream=True), timeout=30) as r:
        chunks = [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ") and x != "data: [DONE]"]
    args = "".join(c["function"]["arguments"] for ch in chunks for c in (ch["choices"][0]["delta"].get("tool_calls") or []))
    assert json.loads(args) == {"to": f"키 {PEM}", "note": f"메모 키 {PEM}"}
    with httpx.stream("POST", masked.gateway + MESSAGES, json={"model": "stub-stream-tool", "max_tokens": 50, "stream": True,
                                                               "messages": [{"role": "user", "content": f"키 {PEM}"}]}, timeout=30) as r:
        events = [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ")]
    partial = "".join(e["delta"]["partial_json"] for e in events
                      if e.get("type") == "content_block_delta" and e["delta"]["type"] == "input_json_delta")
    assert json.loads(partial) == {"to": f"키 {PEM}", "note": f"메모 키 {PEM}"}


def test_f1_arguments_keep_the_models_bytes(masked):
    """텍스트 그대로 복원하므로 모델이 쓴 인자의 모양(공백·순서)이 바뀌지 않는다 — 다음 턴 이력이 같은 바이트다."""
    r = httpx.post(masked.gateway + CHAT, json=chat(f"번호 {PHONE}", "stub-toolcall"))
    args = r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert args == json.dumps({"to": f"번호 {PHONE}"}, ensure_ascii=False)


# ---------- F2 `<` 이스케이프 ----------

def test_f2_surrogate_next_to_escaped_angle_bracket_is_restored(masked):
    r = httpx.post(masked.gateway + CHAT, json=chat(f"번호 <{PHONE}>", "stub-html"))
    assert r.json()["choices"][0]["message"]["content"] == f"[stub] 번호 <{PHONE}>"
    assert audit(masked, r)["pii_suspect"] == 0


# ---------- F3 예약 도메인 ----------

@pytest.mark.parametrize("value", [EMAIL, "kim@example.com", "KIM_99+tag@Mail.Example.COM"])
def test_f3_email_surrogates_use_reserved_domains(value):
    s = TokenVault().token_for("r", "email", value)
    assert s.split("@")[1] in ("example.com", "example.net", "example.org")
    assert [f.kind for f in find_all(s)] == ["email"] and s.lower() != value.lower()


# ---------- F4 헤더·감사 ----------

def test_f4_header_and_audit_show_issued_and_restored(masked):
    r = httpx.post(masked.gateway + CHAT, json=chat(f"번호 {PHONE}, 메일 {EMAIL}", "stub-model"))
    assert r.headers["x-gateway-pii"] == "issued=2 restored=2"
    line = audit(masked, r)
    assert (line["pii_issued"], line["pii_restored"], line["pii_suspect"]) == (2, 2, 0)
    clean = httpx.post(masked.gateway + CHAT, json=chat("연차는 며칠인가요?", "stub-model"))
    assert "x-gateway-pii" not in clean.headers and audit(masked, clean)["pii_issued"] == 0


def test_f4_streaming_header_has_issued_and_audit_has_the_rest(masked):
    with httpx.stream("POST", masked.gateway + CHAT, json=chat(f"번호 {PHONE}", "stub-stream", stream=True), timeout=30) as r:
        assert r.headers["x-gateway-pii"] == "issued=1"
        rid = r.headers["x-gateway-request-id"]
        r.read()
    (line,) = [x for x in masked.log_lines() if x["request_id"] == rid]
    assert (line["pii_issued"], line["pii_restored"], line["pii_suspect"]) == (1, 1, 0)


# ---------- F5 의심 잔여 ----------

def test_f5_last_four_digits_of_a_surrogate_count_as_suspect(masked):
    metric = lambda: next(int(x.split()[-1]) for x in httpx.get(masked.gateway + "/__gateway/metrics", headers=ADMIN).text.splitlines()   # noqa: E731
                          if x.startswith("gateway_pii_suspect_total"))
    before = metric()
    r = httpx.post(masked.gateway + CHAT, json=chat(f"제 번호는 {PHONE}입니다", "stub-last4"))
    answer = r.json()["choices"][0]["message"]["content"]
    assert "6789" not in answer                                           # 사용자는 가짜 번호의 끝자리를 받았다
    assert audit(masked, r)["pii_suspect"] == 1 and metric() == before + 1
    quiet = httpx.post(masked.gateway + CHAT, json=chat(f"제 번호는 {PHONE}입니다", "stub-quiet"))
    assert audit(masked, quiet)["pii_suspect"] == 0 and audit(masked, quiet)["pii_restored"] == 0   # 값을 말하지 않은 답은 의심이 아니다
