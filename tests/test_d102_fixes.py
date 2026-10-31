"""D-102: 독립 리뷰(2026-10-29)로 재현한 게이트웨이 결함 10건의 회귀 테스트.

번호는 D-102 §1의 표와 같다. 각 테스트는 결함이 되살아나면 실패한다(scripts/mutate_d102.py가 그것을 센다).
"""
from __future__ import annotations

import json
import random
import time

import httpx
import pytest

from gateway.detectors import patterns as p
from gateway.detectors.base import Action, Inspection
from gateway.detectors.pii import FINDINGS_LIMIT, PRIORITY, Finding, PIIDetector, find_all
from tests.chain_app import REGISTRY as TEST_REGISTRY

PATH = "/v1/chat/completions"
HEADERS = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def secured(make_stack):
    return make_stack(GATEWAY_DETECTORS="injection_rule_turn,pii_mask")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def chat(messages: list[dict], **extra) -> dict:
    return {"model": "stub-model", "messages": messages, **extra}


# ---------- #1 탐지 건수에 선형 — 결과는 예전 방식과 같다 ----------

def _reference_find_all(text: str) -> list[Finding]:
    """2026-10-29 이전의 겹침 해소 그대로: 후보 전체를 우선순위·길이·위치로 정렬해 탐욕적으로 고른다.
    후보는 `candidates`에서 받는다 — 종류가 늘어도(D-117) 이 테스트는 겹침 해소만 비교한다."""
    cands = [f for found in p.candidates(text).values() for f in found]
    cands.sort(key=lambda f: (PRIORITY[f.kind], -(f.end - f.start), f.start))
    taken: list[Finding] = []
    for f in cands:
        if any(f.start < t.end and t.start < f.end for t in taken):
            continue
        taken.append(f)
    return sorted(taken, key=lambda f: f.start)


SAMPLES = ["010-2345-6789", "900101-1234563", "4111-1111-1111-1111", "kim@example.com",
           "sk-" + "A1b2C3d4" * 6, "9001011234563", "02-123-4567", "연차는 며칠인가요",
           "302-1122-3344-55", "AKIA" + "ABCDEFGHIJKLMNOP", "a@b.co", "1234",
           "124-81-00998", "130111-0006246", "11-20-123456-78", "M12345678", "121.134.5.6", "900101-5234567"]   # D-117


def test_find_all_matches_the_previous_algorithm_on_random_mixes():
    rng = random.Random(20261029)
    for _ in range(400):
        text = "".join(rng.choice(SAMPLES) + rng.choice([" ", "", ", ", "\n", "으로 ", "-"])
                       for _ in range(rng.randint(1, 12)))
        # 겹침 해소만 비교한다 — 가릴지(mask)는 예전 방식에 없던 판단이다(D-116)
        assert [(f.kind, f.start, f.end, f.confidence) for f in find_all(text)] == \
               [(f.kind, f.start, f.end, f.confidence) for f in _reference_find_all(text)], text


def test_find_all_is_linear_in_hit_count():
    text = "010-1234-5678 " * 20_000     # 273KB. 예전 방식은 4초, 1MiB면 60초였다
    t0 = time.perf_counter()
    found = find_all(text)
    assert len(found) == 20_000
    assert time.perf_counter() - t0 < 1.0


@pytest.mark.anyio
async def test_masking_many_hits_is_fast_and_audit_meta_is_capped():
    det = PIIDetector("mask", max_findings=100_000)   # 치환 속도를 본다 — 기본 탐지 상한(5000, D-110)은 test_d110이 본다
    body = json.dumps(chat([{"role": "user", "content": "010-1234-5678 " * 74_000}])).encode()   # 1,011KB — 상한 바로 아래
    t0 = time.perf_counter()
    v = await det.inspect(Inspection(request_id="r", method="POST", path=PATH, headers={}, body=body, session="s"))
    assert time.perf_counter() - t0 < 2.0          # 새 코드 0.2초. 건마다 본문 전체를 복사하던 예전 치환은 4.7초
    assert v.action is Action.TRANSFORM and v.meta["masked"] == 74_000
    assert v.meta["pii"] == {"phone": 74_000}
    assert len(v.meta["findings"]) == FINDINGS_LIMIT
    assert v.meta["findings_omitted"] == 74_000 - FINDINGS_LIMIT
    assert "010-1234-5678" not in v.body.decode("utf-8")


# ---------- #2 클라이언트의 accept-encoding을 상류로 넘기지 않는다 ----------

def test_client_accept_encoding_is_not_forwarded(stack):
    r = httpx.post(f"{stack.gateway}{PATH}", headers={**HEADERS, "Accept-Encoding": "br"},
                   json=chat([{"role": "user", "content": "안녕하세요"}]))
    assert r.status_code == 200
    seen = r.json()["gateway_test"]["accept_encoding"] or ""
    assert seen != "br" and "gzip" in seen      # 게이트웨이의 httpx가 풀 수 있는 것만 알린다


# ---------- #3 응답의 tool_calls 인자도 다음 턴 이력에서 가린다 ----------

def test_tool_call_arguments_are_masked_on_the_next_turn(secured):
    first = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json=chat(
        [{"role": "user", "content": "010-2345-6789로 문자 보내줘"}], model="stub-toolcall")).json()
    assistant = first["choices"][0]["message"]
    assert "010-2345-6789" in assistant["tool_calls"][0]["function"]["arguments"]   # 사용자에게는 복원되어 간다
    second = httpx.post(f"{secured.gateway}{PATH}", headers=HEADERS, json=chat([
        {"role": "user", "content": "010-2345-6789로 문자 보내줘"},
        assistant,
        {"role": "tool", "tool_call_id": "call_1", "content": "sent"},
        {"role": "user", "content": "고마워"}], model="stub-toolcall")).json()
    seen = second["gateway_test"]
    assert seen["tool_args_masked_seen"] and not seen["tool_args_raw_phone_seen"]


# ---------- #4·#5(옛 경로 본문)·#6(캐치올의 헤더 통과)는 D-109로 대상이 없어졌다 ----------


# ---------- #7 OPTIONS는 Chat Completions 본문으로 보지 않는다 ----------

def test_options_on_chat_path_is_not_parsed_or_relayed(stack):
    r = httpx.options(f"{stack.gateway}{PATH}")
    assert r.status_code == 404        # D-109: 허용 목록 밖의 메서드. 본문 파싱 400이 아니다


# ---------- #8 "stream": null ----------

def test_stream_null_is_accepted(stack):
    r = httpx.post(f"{stack.gateway}{PATH}", headers=HEADERS,
                   json=chat([{"role": "user", "content": "안녕하세요"}], stream=None))
    assert r.status_code == 200


# ---------- #9 500에도 요청 ID가 붙는다 ----------

def test_unhandled_error_response_carries_request_id(make_stack):
    boom = make_stack(TEST_REGISTRY, GATEWAY_DETECTORS="test_boom")   # 검사기 내부 예외
    r = httpx.post(f"{boom.gateway}{PATH}", json=chat([{"role": "user", "content": "hi"}]), headers=HEADERS)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    rid = r.headers["x-gateway-request-id"]
    (line,) = [x for x in boom.log_lines() if x["request_id"] == rid]
    assert line["status"] == 500 and line["error"] == "RuntimeError"


# ---------- #10 date·server 헤더를 상류 것까지 둘씩 내보내지 않는다 ----------

def test_upstream_date_and_server_headers_are_not_duplicated(stack):
    r = httpx.post(f"{stack.gateway}{PATH}", json=chat([{"role": "user", "content": "hi"}]), headers=HEADERS)
    assert r.status_code == 200
    assert len(r.headers.get_list("date")) == 1
    assert len(r.headers.get_list("server")) == 1
