"""4-B 완료 조건 검증: 요청 1건 → 감사 로그 1줄, 그리고 원문은 남지 않는다."""
import httpx
import pytest

PATH_ = "/api/v1/workspace/demo-slug/chat"
SECRET = "제 주민등록번호는 900101-1234567 입니다"
BODY = {"message": SECRET, "mode": "query", "sessionId": "eval-xyz"}
HDR = {"Authorization": "Bearer super-secret-key", "Content-Type": "application/json"}

REQUIRED = {"ts", "request_id", "method", "path", "query", "status",
            "total_ms", "upstream_ms", "gateway_ms",
            "req_bytes", "req_sha256_12", "res_bytes", "blocked", "client"}


@pytest.fixture(scope="module")
def one_request(stack):
    r = httpx.post(f"{stack.gateway}{PATH_}?k=v", json=BODY, headers=HDR)
    assert r.status_code == 200
    return stack, r


def test_one_request_one_line(one_request):
    stack, _ = one_request
    lines = stack.log_lines()
    assert len(lines) == 1
    assert REQUIRED <= set(lines[0])


def test_request_id_matches_response_header(one_request):
    stack, r = one_request
    assert stack.log_lines()[0]["request_id"] == r.headers["X-Gateway-Request-Id"]


def test_no_plaintext_body_in_log(one_request):
    """가장 중요한 테스트. 로그 파일 어디에도 원문·API 키가 없어야 한다."""
    stack, _ = one_request
    raw = stack.log_path.read_text(encoding="utf-8")
    assert SECRET not in raw
    assert "900101-1234567" not in raw
    assert "super-secret-key" not in raw
    rec = stack.log_lines()[0]
    assert rec["req_bytes"] > 0
    assert len(rec["req_sha256_12"]) == 12   # 지문은 남되 복원은 불가


def test_latency_split_is_consistent(one_request):
    """EVAL 4절: 종단 = 타겟 호출 + 게이트웨이 내부. 세 값이 서로 맞아야 한다."""
    stack, _ = one_request
    rec = stack.log_lines()[0]
    assert rec["upstream_ms"] is not None
    assert rec["gateway_ms"] >= 0
    assert rec["upstream_ms"] <= rec["total_ms"]
    assert abs(rec["gateway_ms"] + rec["upstream_ms"] - rec["total_ms"]) < 0.01


def test_blocked_flag_defaults_false(one_request):
    """EVAL 3.3의 자동 판정 필드. 검사기가 없는 지금은 항상 False."""
    stack, _ = one_request
    assert stack.log_lines()[0]["blocked"] is False


def test_internal_paths_are_not_logged(stack):
    """헬스체크는 지연 통계를 오염시키므로 기록하지 않는다."""
    before = len(stack.log_lines())
    for _ in range(3):
        httpx.get(f"{stack.gateway}/__gateway/health")
    assert len(stack.log_lines()) == before
