"""4-A 완료 조건 검증: 게이트웨이 경유 응답 == 타겟 직접 호출 응답.

이 파일이 통과하는 한 ASR 변화의 원인은 방어 로직뿐이다.
프록시가 요청을 망가뜨려서 생긴 ASR 감소는 측정이 아니라 거짓말이다.
"""
import httpx

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
