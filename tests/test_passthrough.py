"""4-A 완료 조건 검증: 게이트웨이 경유 응답 == 타겟 직접 호출 응답.

이 파일이 통과하는 한 ASR 변화의 원인은 방어 로직뿐이다.
프록시가 요청을 망가뜨려서 생긴 ASR 감소는 측정이 아니라 거짓말이다.
"""
import httpx
import pytest

PATH_ = "/api/v1/workspace/demo-slug/chat"
BODY = {"message": "안녕하세요, 연차는 며칠인가요?", "mode": "query", "sessionId": "eval-abc123"}
HDR = {"Authorization": "Bearer test-key-123", "Content-Type": "application/json"}


def test_health(stack):
    r = httpx.get(f"{stack.gateway}/__gateway/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_passthrough_identical(stack):
    """4-A의 핵심. 직접 호출과 프록시 경유가 완전히 같아야 한다."""
    direct = httpx.post(f"{stack.target}{PATH_}?x=1&y=한글", json=BODY, headers=HDR)
    proxied = httpx.post(f"{stack.gateway}{PATH_}?x=1&y=한글", json=BODY, headers=HDR)
    assert direct.status_code == proxied.status_code == 200
    assert direct.json() == proxied.json(), "게이트웨이가 요청/응답을 변형했다"


def test_response_headers_handled_correctly(stack):
    """헤더 정책을 못박는다. 셋 다 의도된 동작이며 하나라도 어긋나면 응답이 깨진다."""
    direct = httpx.post(f"{stack.target}{PATH_}", json=BODY, headers=HDR)
    proxied = httpx.post(f"{stack.gateway}{PATH_}", json=BODY, headers=HDR)

    # (1) 의미 있는 헤더는 그대로 전달된다
    assert proxied.headers["content-type"] == direct.headers["content-type"]

    # (2) content-encoding은 반드시 제거한다.
    #     타겟은 gzip으로 보냈지만 httpx가 이미 풀었다. 헤더를 그대로 넘기면
    #     클라이언트가 생 텍스트를 gzip으로 알고 다시 풀려다 깨진다.
    assert direct.headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in proxied.headers

    # (3) 상관관계 추적용 헤더 하나만 새로 붙인다 (본문은 건드리지 않는다)
    assert "x-gateway-request-id" in proxied.headers


def test_body_and_auth_preserved(stack):
    echo = httpx.post(f"{stack.gateway}{PATH_}", json=BODY, headers=HDR).json()["echo"]
    assert echo["body"] == BODY  # 한글·sessionId 포함 본문 무손상 (D-013)
    assert echo["auth"] == HDR["Authorization"]  # API 키가 타겟까지 전달됨
    assert echo["path"] == PATH_


def test_query_string_preserved(stack):
    echo = httpx.post(f"{stack.gateway}{PATH_}?a=1&b=2", json=BODY, headers=HDR).json()["echo"]
    assert echo["query"] == "a=1&b=2"


def test_status_code_passthrough(stack):
    """타겟의 404를 200으로 바꾸거나 삼키지 않는다."""
    assert httpx.get(f"{stack.gateway}/no/such/path").status_code == 404


# ---------- D-099: 본문 크기 상한 ----------
# 상한이 없으면 큰 요청 하나가 메모리와 검사기 시간을 독차지한다(워커 1개).
# 시험은 상한을 2KB로 낮춘 게이트웨이로 한다. 기본값은 1MiB다.

SMALL_LIMIT = 2048


@pytest.fixture(scope="module")
def small(make_stack):
    return make_stack(GATEWAY_MAX_BODY_BYTES=str(SMALL_LIMIT), GATEWAY_DETECTORS="injection_rule,pii_mask")


def _line(stack, r):
    return next(x for x in stack.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"])


def test_over_limit_is_413_and_never_reaches_target(small):
    big = {**BODY, "message": "가" * 1000}                    # UTF-8 3바이트 x 1000 > 2KB
    r = httpx.post(f"{small.gateway}{PATH_}", json=big, headers=HDR)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "request_too_large"
    line = _line(small, r)
    assert line["status"] == 413 and line["upstream_ms"] is None
    assert line["req_bytes"] > SMALL_LIMIT and line["detectors"] == [], "검사기도 돌지 않는다"


def test_over_limit_without_content_length_is_413(small):
    """길이 헤더 없이(chunked) 보내도 같은 상한이 걸린다."""
    r = httpx.post(f"{small.gateway}{PATH_}", headers=HDR,
                   content=(b"x" * 1024 for _ in range(4)))
    assert r.status_code == 413


def test_under_limit_still_passes_through(small):
    r = httpx.post(f"{small.gateway}{PATH_}", json=BODY, headers=HDR)
    assert r.status_code == 200 and r.json()["echo"]["body"] == BODY
