"""D-109: 보안 경계 — 경로·헤더 허용 목록, 관리 엔드포인트. 번호 B1~B8은 D-109 §4의 표와 같다."""
from __future__ import annotations

import os
import subprocess
import sys

import httpx
import pytest

from tests.conftest import ADMIN, free_port

KEY = {"Authorization": "Bearer client-key"}


@pytest.fixture(scope="module")
def custody(make_stack):
    """운영 모양: 클라이언트 키 + 상류 키."""
    return make_stack(GATEWAY_CLIENT_KEYS="c=client-key", GATEWAY_UPSTREAM_KEY="upstream-key")


@pytest.fixture(scope="module")
def keyed(make_stack):
    """인증은 켜고 상류 키는 없다(로컬 OpenAI 호환 서버 앞)."""
    return make_stack(GATEWAY_CLIENT_KEYS="c=client-key")


def hits(stack) -> list[list[str]]:
    return httpx.get(f"{stack.target}/__stub/hits").json()["hits"]


def audit(stack, r: httpx.Response) -> dict:
    (line,) = [x for x in stack.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"]]
    return line


def upstream_saw(r: httpx.Response) -> dict:
    """스텁 GET /v1/models가 돌려준, 상류가 받은 요청 헤더."""
    assert r.status_code == 200, r.text
    return r.json()["gateway_test"]["headers"]


# ---------- B1·B2 경로 허용 목록 ----------

@pytest.mark.parametrize("method, path", [("DELETE", "/v1/files/x"), ("POST", "/v1/fine_tuning/jobs"),
                                          ("GET", "/v1/organization/users"), ("POST", "/api/v1/workspace/demo/chat"),
                                          ("POST", "/v1/messages/count_tokens")])
def test_b1_unknown_paths_are_404_and_never_reach_upstream(custody, method, path):
    before = len(hits(custody))
    r = httpx.request(method, custody.gateway + path, headers=KEY, json={"model": "m"})
    assert r.status_code == 404
    assert len(hits(custody)) == before, "허용 목록 밖의 경로가 상류에 연결됐다"
    line = audit(custody, r)
    assert line["status"] == 404 and line["upstream_ms"] is None and line["api"] is None


@pytest.mark.parametrize("method, path", [("GET", "/v1/chat/completions"), ("PUT", "/v1/responses"),
                                          ("POST", "/v1/models"), ("OPTIONS", "/v1/messages")])
def test_b2_other_methods_on_known_paths_are_404_in_the_api_error_shape(custody, method, path):
    before = len(hits(custody))
    r = httpx.request(method, custody.gateway + path, headers=KEY)
    assert r.status_code == 404
    if path == "/v1/messages":
        assert r.json() == {"type": "error", "error": {"type": "not_found_error", "message": "not found"}}
    else:
        assert r.json()["error"]["code"] == "not_found"
    assert len(hits(custody)) == before


# ---------- B3·B4 요청 헤더 ----------

def test_b3_models_gets_the_upstream_key_in_the_callers_format(custody):
    r = httpx.get(custody.gateway + "/v1/models", headers=KEY)
    assert r.json()["data"][0]["id"] == "stub-model"
    seen = upstream_saw(r)
    assert seen["authorization"] == "Bearer upstream-key" and "x-api-key" not in seen
    seen = upstream_saw(httpx.get(custody.gateway + "/v1/models",
                                  headers={"x-api-key": "client-key", "anthropic-version": "2023-06-01"}))
    assert seen["x-api-key"] == "upstream-key" and "authorization" not in seen      # Anthropic SDK의 models.list
    assert seen["anthropic-version"] == "2023-06-01"
    assert "client-key" not in str(seen)


def test_b4_client_headers_outside_the_allow_list_do_not_reach_upstream(custody):
    """상류가 앞 요청에 준 set-cookie도 다음 요청에 붙지 않는다 — 공유 httpx 클라이언트의 쿠키 저장소를 껐다."""
    httpx.get(custody.gateway + "/v1/models", headers=KEY)          # 스텁이 set-cookie를 준다
    seen = upstream_saw(httpx.get(custody.gateway + "/v1/models", headers={
        **KEY, "Cookie": "sid=1", "OpenAI-Organization": "org-client", "OpenAI-Project": "proj-client",
        "X-Forwarded-For": "1.2.3.4", "X-Stainless-OS": "MacOS", "OpenAI-Beta": "assistants=v2",
        "Idempotency-Key": "idem-1"}))
    for name in ("cookie", "openai-organization", "openai-project", "x-forwarded-for", "x-stainless-os"):
        assert name not in seen, name
    assert seen["openai-beta"] == "assistants=v2" and seen["idempotency-key"] == "idem-1"   # 허용 목록은 넘긴다


# ---------- B5 응답 헤더 ----------

def test_b5_upstream_response_headers_are_filtered_and_request_id_is_audited(custody):
    r = httpx.get(custody.gateway + "/v1/models", headers=KEY)
    for name in ("openai-organization", "set-cookie", "x-request-id", "openai-processing-ms"):
        assert name not in r.headers, name
    assert r.headers["content-type"].startswith("application/json") and "x-gateway-request-id" in r.headers
    assert audit(custody, r)["upstream_request_id"] == "req_stub_models"


# ---------- B6 통과 모드 ----------

def test_b6_passthrough_mode_forwards_the_clients_own_account(stack):
    """인증을 끈 로컬 실험(상류 키 없음): 클라이언트의 공급자 키와 조직 헤더가 그대로 간다. cookie는 여전히 뗀다."""
    seen = upstream_saw(httpx.get(stack.gateway + "/v1/models", headers={
        "Authorization": "Bearer sk-client-own", "OpenAI-Organization": "org-client", "Cookie": "sid=1"}))
    assert seen["authorization"] == "Bearer sk-client-own" and seen["openai-organization"] == "org-client"
    assert "cookie" not in seen


def test_b6_auth_on_without_upstream_key_keeps_the_gateway_key_home(keyed):
    seen = upstream_saw(httpx.get(keyed.gateway + "/v1/models", headers={**KEY, "OpenAI-Organization": "org-client"}))
    assert "authorization" not in seen and "x-api-key" not in seen, "게이트웨이 키가 상류로 샜다"
    assert seen["openai-organization"] == "org-client"


# ---------- B7 기동 ----------

def test_b7_auth_off_with_upstream_key_does_not_boot():
    env = {**os.environ, "GATEWAY_AUTH": "off", "GATEWAY_UPSTREAM_KEY": "k", "GATEWAY_LOG_PATH": "-", "GATEWAY_PII": "off"}
    p = subprocess.run([sys.executable, "-m", "uvicorn", "gateway.main:app", "--port", str(free_port())],
                       env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode != 0 and "GATEWAY_UPSTREAM_KEY" in p.stderr


# ---------- B8 관리 엔드포인트 ----------

@pytest.fixture(scope="module")
def no_admin(make_stack):
    return make_stack(GATEWAY_ADMIN_KEY="")


def test_b8_health_is_status_only(custody):
    r = httpx.get(custody.gateway + "/__gateway/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/__gateway/info", "/__gateway/metrics"])
def test_b8_admin_endpoints_need_the_admin_key(no_admin, stack, path):
    assert httpx.get(no_admin.gateway + path).status_code == 404
    assert httpx.get(no_admin.gateway + path, headers=ADMIN).status_code == 404     # 관리 키가 없는 게이트웨이는 아무도 못 본다
    assert httpx.get(stack.gateway + path).status_code == 404
    assert httpx.get(stack.gateway + path, headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert httpx.get(stack.gateway + path, headers=ADMIN).status_code == 200


# ---------- B9 컨테이너 로그 ----------

def test_b9_container_command_turns_off_the_access_log():
    """uvicorn 접근 로그는 쿼리 문자열을 값까지 찍는다(`?phone=010-…`) — 감사 로그가 일부러 빼는 값이 컨테이너 로그에 남고
    stdout이 감사 JSONL과 섞인다(2026-10-30 컨테이너 확인에서 재현). 이미지의 기본 명령은 접근 로그를 끈다."""
    import json as _json
    from pathlib import Path
    dockerfile = (Path(__file__).resolve().parents[1] / "gateway" / "Dockerfile").read_text(encoding="utf-8")
    (cmd,) = [line for line in dockerfile.splitlines() if line.startswith("CMD ")]
    assert "--no-access-log" in _json.loads(cmd[4:])
