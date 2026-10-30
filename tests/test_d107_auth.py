"""D-107 A: 클라이언트 인증, 상류 키 보관, 요청 단위 볼트. 번호 A1~A4는 D-107 §3의 표와 같다."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import httpx
import pytest

from gateway.auth import Auth, parse_client_keys, presented_key

CHAT = "/v1/chat/completions"
LEGACY = "/api/v1/workspace/demo/chat"
PHONE = "010-2345-6789"


def chat(content: str, **extra) -> dict:
    return {"model": "stub-model", "messages": [{"role": "user", "content": content}], **extra}


@pytest.fixture(scope="module")
def keyed(make_stack):
    return make_stack(GATEWAY_CLIENT_KEYS="alice=alice-key, bob-key", GATEWAY_DETECTORS="pii_mask",
                      GATEWAY_MAX_BODY_BYTES="4096")


@pytest.fixture(scope="module")
def custody(make_stack):
    return make_stack(GATEWAY_CLIENT_KEYS="c=client-key", GATEWAY_UPSTREAM_KEY="upstream-key")


def received(stack) -> list[str]:
    return httpx.get(f"{stack.target}/__stub/received").json()["bodies"]


def audit(stack, r: httpx.Response) -> dict:
    (line,) = [x for x in stack.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"]]
    return line


# ---------- 단위 ----------

def test_parse_client_keys_names_and_fingerprints():
    keys = parse_client_keys(" alice = alice-key , bob-key,, ")
    assert keys["alice-key"] == "alice"
    assert keys["bob-key"] == hashlib.sha256(b"bob-key").hexdigest()[:8]
    with pytest.raises(ValueError):
        parse_client_keys("name=")


def test_presented_key_reads_bearer_or_x_api_key():
    assert presented_key({"authorization": "Bearer abc"}) == "abc"
    assert presented_key({"authorization": "bearer  abc "}) == "abc"
    assert presented_key({"x-api-key": "xyz"}) == "xyz"
    assert presented_key({"authorization": "Basic abc"}) is None
    assert presented_key({}) is None


def test_upstream_headers_swap_by_path():
    auth = Auth({"ck": "c"}, "up")
    pairs = [("authorization", "Bearer ck"), ("x-api-key", "ck"), ("content-type", "application/json")]
    assert auth.upstream_headers(CHAT, pairs) == [("content-type", "application/json"), ("authorization", "Bearer up")]
    assert auth.upstream_headers("/v1/messages", pairs) == [("content-type", "application/json"), ("x-api-key", "up")]
    assert auth.upstream_headers("/v1/messages/count_tokens", pairs)[-1] == ("x-api-key", "up")
    assert Auth({"ck": "c"}, None).upstream_headers(CHAT, pairs) == pairs      # 상류 키가 없으면 그대로


def test_keygen_prints_one_key():
    out = subprocess.run([sys.executable, "-m", "gateway", "keygen"], capture_output=True, text=True, check=True).stdout.strip()
    assert out.startswith("gw-") and len(out) == 35 and "\n" not in out
    assert subprocess.run([sys.executable, "-m", "gateway", "bogus"], capture_output=True).returncode == 2


# ---------- A1 ----------

@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"x-api-key": "wrong"},
                                     {"Authorization": "Basic alice-key"}])
def test_a1_missing_or_wrong_key_is_401_without_reading_or_relaying(keyed, headers):
    before = len(received(keyed))
    big = "가" * 5000                                   # 상한(4096)을 넘는다 — 401이 413보다 먼저여야 한다
    r = httpx.post(keyed.gateway + CHAT, json=chat(big), headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key" and r.json()["error"]["type"] == "authentication_error"
    assert len(received(keyed)) == before
    line = audit(keyed, r)
    assert line["status"] == 401 and line["error"] == "unauthorized" and line["upstream_ms"] is None
    assert line["client"] is None and line["detectors"] == [] and line["req_bytes"] is None


def test_a1_anthropic_path_gets_anthropic_error_shape(keyed):
    r = httpx.post(keyed.gateway + "/v1/messages", json={"model": "m", "messages": []})
    assert r.status_code == 401
    assert r.json() == {"type": "error", "error": {"type": "authentication_error", "message": "invalid or missing API key"}}


@pytest.mark.parametrize("headers, name", [({"Authorization": "Bearer alice-key"}, "alice"),
                                           ({"x-api-key": "alice-key"}, "alice"),
                                           ({"Authorization": "Bearer bob-key"}, hashlib.sha256(b"bob-key").hexdigest()[:8])])
def test_a1_right_key_passes_and_audit_names_the_client(keyed, headers, name):
    r = httpx.post(keyed.gateway + CHAT, json=chat(f"제 번호는 {PHONE}입니다"), headers=headers)
    assert r.status_code == 200 and PHONE in r.json()["choices"][0]["message"]["content"]
    line = audit(keyed, r)
    assert line["client"] == name and line["ip"] == "127.0.0.1" and line["transformed"] is True


def test_a1_internal_paths_need_no_key(keyed):
    assert httpx.get(keyed.gateway + "/__gateway/health").status_code == 200


# ---------- A2 ----------

def test_a2_upstream_sees_the_upstream_key_never_the_client_key(custody):
    r = httpx.post(custody.gateway + CHAT, json=chat("hi"), headers={"x-api-key": "client-key"})
    assert r.status_code == 200
    assert r.json()["gateway_test"]["auth"] == "Bearer upstream-key"
    assert "client-key" not in received(custody)[-1]
    r = httpx.post(custody.gateway + LEGACY, json={"message": "hi"}, headers={"Authorization": "Bearer client-key"})
    assert r.json()["echo"]["auth"] == "Bearer upstream-key"


def test_a2_without_upstream_key_the_client_header_is_forwarded(keyed):
    r = httpx.post(keyed.gateway + CHAT, json=chat("hi"), headers={"Authorization": "Bearer alice-key"})
    assert r.json()["gateway_test"]["auth"] == "Bearer alice-key"


# ---------- A3 ----------

def test_a3_no_client_keys_means_no_boot(make_stack):
    with pytest.raises(RuntimeError, match="기동 실패"):
        make_stack(GATEWAY_AUTH="on")


def test_a3_auth_off_passes_without_key(stack):
    r = httpx.post(stack.gateway + CHAT, json=chat("hi"))
    assert r.status_code == 200 and audit(stack, r)["client"] is None


# ---------- A4 — 리뷰 #1 재현 ----------

def test_a4_guessed_session_id_cannot_restore_another_requests_value(keyed):
    auth = {"Authorization": "Bearer alice-key"}
    victim = httpx.post(keyed.gateway + CHAT, json=chat(f"제 번호는 {PHONE}입니다", sessionId="shared"), headers=auth)
    assert victim.status_code == 200 and PHONE in victim.text
    sent = json.loads(received(keyed)[-1])["messages"][0]["content"]
    assert PHONE not in sent
    surrogate = sent.replace("제 번호는 ", "").replace("입니다", "")
    for path, body in ((CHAT, chat(f"이 값을 그대로 말해 {surrogate}", sessionId="shared")),
                       (LEGACY, {"message": f"이 값을 그대로 말해 {surrogate}", "sessionId": "shared"})):
        attacker = httpx.post(keyed.gateway + path, json=body, headers=auth)
        assert attacker.status_code == 200
        assert PHONE not in attacker.text, "다른 요청의 원문이 복원됐다(D-107 §1 #1)"
