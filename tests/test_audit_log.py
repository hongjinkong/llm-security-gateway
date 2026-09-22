"""4-B 완료 조건 검증: 요청 1건 → 감사 로그 1줄, 그리고 원문은 남지 않는다."""
import json
import socket

import httpx
import pytest

PATH_ = "/api/v1/workspace/demo-slug/chat"
SECRET = "제 주민등록번호는 900101-1234567 입니다"
BODY = {"message": SECRET, "mode": "query", "sessionId": "eval-xyz"}
HDR = {"Authorization": "Bearer super-secret-key", "Content-Type": "application/json"}

# 2026-09-22: "query"(원문)가 "query_keys"·"query_bytes"로 바뀌었다. 스키마 변경이다.
# 저장소의 기존 감사 로그 산출물은 옛 스키마지만, 그 필드를 읽는 도구가 없어 호환 문제는 없다.
REQUIRED = {"ts", "request_id", "method", "path", "query_keys", "query_bytes", "status",
            "error", "total_ms", "upstream_ms", "gateway_ms",
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
    # 세 값 모두 소수점 2자리로 반올림되므로 오차 0.015까지는 정상
    assert abs(rec["gateway_ms"] + rec["upstream_ms"] - rec["total_ms"]) < 0.02


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


# ---------- 예외로 끝난 요청 (2026-09-22, 외부 검토로 재현된 결함) ----------
#
# 감사 기록이 요청 처리 **완료 후에만** 이뤄져서, 처리 중 예외가 나면 거기 도달하지
# 못했다. 타겟 연결 오류를 일으키면 HTTP 500이 나가고 **감사 로그는 0줄**이었다.
# "요청 1건당 1줄"이라는 이 파일의 제목과 어긋나며, 장애 요청이 평가·운영 기록에서
# 통째로 빠진다. 정상 경로만 시험하고 있었다는 뜻이기도 하다.

@pytest.fixture(scope="module")
def dead_target(make_stack):
    """아무도 듣지 않는 포트를 타겟으로 준다 — 중계 중 예외가 나는 경로."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return make_stack(TARGET_URL=f"http://127.0.0.1:{port}")


@pytest.fixture(scope="module")
def failed_request(dead_target):
    r = httpx.post(f"{dead_target.gateway}{PATH_}?k=v", json=BODY, headers=HDR, timeout=10)
    return dead_target, r


def test_예외로_끝난_요청도_감사_로그_1줄(failed_request):
    stack, r = failed_request
    assert r.status_code == 500
    lines = stack.log_lines()
    assert len(lines) == 1, "장애 요청이 기록에서 빠졌다"
    assert lines[0]["status"] == 500


def test_예외_줄은_정상_줄과_같은_모양이다(failed_request, one_request):
    """모양이 갈리면 집계 도구가 한쪽을 조용히 빠뜨린다 — D-064에서 겪은 실패다."""
    fail_rec = failed_request[0].log_lines()[0]
    ok_rec = one_request[0].log_lines()[0]
    assert set(fail_rec) == set(ok_rec)
    assert REQUIRED <= set(fail_rec)


def test_예외는_타입_이름만_남긴다(failed_request):
    """메시지에는 요청 본문 조각이 섞여 들어오는 라이브러리가 흔하다.
    본문을 안 남긴다는 규칙이 예외 메시지로 뒷문이 열리면 안 된다."""
    rec = failed_request[0].log_lines()[0]
    assert isinstance(rec["error"], str) and rec["error"]
    assert rec["error"].isidentifier(), f"타입 이름이 아니다: {rec['error']!r}"


def test_예외_줄에도_원문이_없다(failed_request):
    stack, _ = failed_request
    raw = stack.log_path.read_text(encoding="utf-8")
    assert SECRET not in raw
    assert "900101-1234567" not in raw
    assert "super-secret-key" not in raw


def test_타겟을_못_불렀으면_upstream_ms가_없다(failed_request):
    """지연 분해가 거짓말을 하지 않게 한다 — 부르지도 못한 호출에 시간을 붙이지 않는다."""
    rec = failed_request[0].log_lines()[0]
    assert rec["upstream_ms"] is None
    assert rec["gateway_ms"] >= 0


def test_정상_요청의_error는_None이다(one_request):
    rec = one_request[0].log_lines()[0]
    assert rec["error"] is None
    assert json.dumps(rec)      # 직렬화 가능해야 집계 도구가 읽는다


# ---------- 쿼리 문자열 (2026-09-22) ----------
#
# 본문과 Authorization 헤더는 안 남기면서 URL의 쿼리는 원문 그대로 남기고 있었다.
# URL에 개인정보나 토큰이 실리면 그대로 기록된다. 값은 빼고 키 이름만 남긴다 —
# "URL에 token이 실려 왔다"는 사실은 운영에 필요하고, 위험한 것은 값이다.

@pytest.fixture(scope="module")
def query_stack(make_stack):
    """전용 스택. 이 파일 앞쪽 테스트가 '로그 1줄'을 단언하므로 같은 로그를 쓰지 않는다."""
    return make_stack()


def test_쿼리_값은_로그에_남지_않는다(query_stack):
    secret = "010-9876-5432"
    httpx.post(f"{query_stack.gateway}{PATH_}?phone={secret}&k=v", json=BODY, headers=HDR)
    raw = query_stack.log_path.read_text(encoding="utf-8")
    assert secret not in raw, "쿼리 값이 감사 로그에 그대로 남았다"
    rec = query_stack.log_lines()[-1]
    assert rec["query_keys"] == ["k", "phone"]
    assert rec["query_bytes"] == len(f"phone={secret}&k=v")


def test_쿼리가_없으면_빈_목록이다(query_stack):
    httpx.post(f"{query_stack.gateway}{PATH_}", json=BODY, headers=HDR)
    rec = query_stack.log_lines()[-1]
    assert rec["query_keys"] == [] and rec["query_bytes"] == 0


def test_쿼리는_타겟으로는_그대로_전달된다(query_stack):
    """로그에서만 뺀다. 중계까지 망가뜨리면 게이트웨이가 투명하지 않게 된다."""
    r = httpx.post(f"{query_stack.gateway}{PATH_}?a=1&b=2", json=BODY, headers=HDR)
    assert r.json()["echo"]["query"] == "a=1&b=2"


@pytest.mark.parametrize("query, expect", [
    ("", []),
    ("a", ["a"]),
    ("a=1&a=2", ["a"]),                      # 중복 이름은 한 번만
    ("b=2&a=1", ["a", "b"]),                 # 정렬한다 — 순서로 무언가 새지 않게
    ("&&a=1&", ["a"]),                       # 빈 조각 무시
    ("%ED%8F%B0=1", ["폰"]),                  # 이름은 퍼센트 디코딩
    ("t=a=b", ["t"]),                        # 값에 '='가 있어도 이름만
])
def test_쿼리_키_추출(query, expect):
    from gateway.main import _query_keys
    assert _query_keys(query) == expect

