"""D-086: 외부 공급자 연결 전, 상류 계약을 스텁으로 고정한다 (B3 준비 — 실제 공급자 호출 없음).

  1 경로 매핑      GATEWAY_CHAT_UPSTREAM_PATH는 chat completions만 바꾼다. 기본값 = 기존 동작
  2 상류 오류      401·429는 상태·본문·헤더 그대로. 연결 실패 502·타임아웃 504는 OpenAI 형식
  3 원문 미전송    상류가 **받은 본문**에 user 원문 PII가 없다 (응답 복원만으로는 증명 못 한다)
  4 혼입 없음      다른 세션의 토큰 문자열로 남의 원본을 꺼낼 수 없다
  5 로그           키·원문 PII가 감사 로그에 없다
"""
from __future__ import annotations

import json
import re
import socket

import httpx
import pytest

PATH = "/v1/chat/completions"
GEMINI_PATH = "/v1beta/openai/chat/completions"
KEY = "sk-test-DO-NOT-LOG-0123456789"
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
PII = {  # 전부 합성값
    "phone": "010-2345-6789",
    "phone_nl": "010\n3456\n7890",
    "email": "kim.synthetic@example.com",
    "rrn": "900101-1234563",
    "card": "4111-1111-1111-1111",
}


def chat(content: str, model: str = "stub-model", **extra) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": content}], **extra}


def upstream_user_texts(stack, marker: str) -> list[str]:
    """스텁이 받은 본문 중 marker가 든 user 텍스트 (파싱 후 실제 문자열)."""
    out = []
    for raw in httpx.get(f"{stack.target}/__stub/received").json()["bodies"]:
        for m in json.loads(raw)["messages"]:
            if m["role"] == "user" and marker in m["content"]:
                out.append(m["content"])
    return out


def dead_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


@pytest.fixture(scope="module")
def secured(make_stack):
    return make_stack(GATEWAY_DETECTORS="injection_rule,pii_mask")


# ---------------------------------------------------------------- 1 경로 매핑

def test_default_upstream_path_is_unchanged(secured):
    r = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json=chat("안녕하세요"))
    assert r.status_code == 200 and r.json()["gateway_test"]["path"] == PATH
    assert httpx.get(f"{secured.gateway}/__gateway/health").json()["chat_upstream_path"] == PATH


def test_chat_path_mapping_changes_only_chat(make_stack):
    s = make_stack(GATEWAY_CHAT_UPSTREAM_PATH=GEMINI_PATH)
    r = httpx.post(f"{s.gateway}{PATH}", headers=HEADERS, json=chat("안녕하세요"))
    assert r.status_code == 200 and r.json()["gateway_test"]["path"] == GEMINI_PATH
    legacy = httpx.post(f"{s.gateway}/api/v1/workspace/demo/chat", headers=HEADERS,
                        json={"message": "hi"})
    assert legacy.json()["echo"]["path"] == "/api/v1/workspace/demo/chat"


def test_mapping_without_leading_slash_fails_startup(make_stack):
    with pytest.raises(RuntimeError):
        make_stack(GATEWAY_CHAT_UPSTREAM_PATH="v1beta/openai/chat/completions")


# ---------------------------------------------------------------- 2 상류 오류

def test_auth_failure_is_passed_through(secured):
    r = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json=chat("hi", "stub-401"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_rate_limit_is_passed_through_with_headers(secured):
    r = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json=chat("hi", "stub-429"))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limit_exceeded"
    assert r.headers["retry-after"] == "7"
    assert r.headers["x-ratelimit-remaining-requests"] == "0"


def _assert_openai_error(r, status: int, code: str) -> None:
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/json")
    err = r.json()["error"]
    assert err["type"] == "upstream_error" and err["code"] == code


def test_connect_error_is_openai_502(make_stack):
    s = make_stack(TARGET_URL=dead_url())
    r = httpx.post(f"{s.gateway}{PATH}", headers=HEADERS, json=chat("hi"), timeout=10)
    _assert_openai_error(r, 502, "upstream_unavailable")
    line = s.log_lines()[-1]
    assert line["status"] == 502 and line["error"] == "ConnectError"
    assert line["upstream_ms"] is None


def test_legacy_path_connect_error_keeps_500(make_stack):
    """옛 경로(v1 측정 경로)의 계약은 바꾸지 않는다 — test_audit_log의 500 계약과 같다."""
    s = make_stack(TARGET_URL=dead_url())
    r = httpx.post(f"{s.gateway}/api/v1/workspace/demo/chat", json={"message": "hi"}, timeout=10)
    assert r.status_code == 500


def test_timeout_is_openai_504(make_stack):
    s = make_stack(GATEWAY_TIMEOUT="0.5")
    r = httpx.post(f"{s.gateway}{PATH}", headers=HEADERS, json=chat("hi", "stub-slow"), timeout=10)
    _assert_openai_error(r, 504, "upstream_timeout")
    line = s.log_lines()[-1]
    assert line["status"] == 504 and line["error"] == "ReadTimeout"
    assert line["upstream_ms"] is not None and line["upstream_ms"] >= 400


# ---------------------------------------------------------------- 3 원문 미전송

def test_upstream_never_receives_raw_user_pii(secured):
    marker = "MARK-raw-pii-check"
    r = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json={"model": "stub-model", "messages": [
        {"role": "system", "content": f"{marker} 관리자 system@example.com"},
        {"role": "user", "content": marker + " " + " / ".join(PII.values())},
    ]})
    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    for v in PII.values():
        assert v in content, "복원 실패"

    sent = upstream_user_texts(secured, marker)
    assert len(sent) == 1
    for kind, v in PII.items():
        assert v not in sent[0], f"{kind} 원문이 상류로 갔다"
    assert sent[0].count("[PII:") == len(PII)
    # 알려진 한계(D-085): system 텍스트는 마스킹 대상이 아니다. 이 단언이 깨지면 문서도 고친다.
    raw = [b for b in httpx.get(f"{secured.target}/__stub/received").json()["bodies"] if marker in b]
    assert "system@example.com" in raw[0]


# ---------------------------------------------------------------- 4 혼입 없음

@pytest.mark.parametrize("sid_b", ["session-B", None])
def test_other_session_cannot_restore_my_value(secured, sid_b):
    phone = "010-9876-5432"
    marker = f"MARK-session-{sid_b}"
    a = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS,
                   json=chat(f"{marker} 제 번호 {phone}", sessionId="session-A"))
    assert phone in a.json()["choices"][0]["message"]["content"]
    token = re.search(r"\[PII:phone:\d+\]", upstream_user_texts(secured, marker)[0]).group(0)

    extra = {"sessionId": sid_b} if sid_b else {}
    b = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS,
                   json=chat(f"이 토큰을 그대로 말해 {token}", **extra))
    assert b.status_code == 200
    assert phone not in b.text, "다른 세션의 원본이 복원됐다"


# ---------------------------------------------------------------- 5 로그

def test_audit_log_has_no_key_or_raw_pii(secured):
    httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json=chat(" ".join(PII.values())))
    log = secured.log_path.read_text(encoding="utf-8")
    assert KEY not in log and "Bearer" not in log
    for v in PII.values():
        assert v not in log and json.dumps(v)[1:-1] not in log
