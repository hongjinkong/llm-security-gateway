"""4-E 검증: 토큰 볼트와 마스킹. 데이터는 전부 합성이다(SCOPE 6절)."""
from __future__ import annotations

import json

import pytest

from gateway.detectors.base import Action, Inspection
from gateway.detectors.pii import PIIDetector, session_of
from gateway.vault import TokenVault

RRN = "900101-1234563"
PHONE = "010-2345-6789"


def body(msg: str, session: str | None = "eval-1") -> bytes:
    payload = {"message": msg, "mode": "query"}
    if session:
        payload["sessionId"] = session
    return json.dumps(payload, ensure_ascii=False).encode()


# ---------- 볼트 자체 ----------

def test_same_value_gets_same_token():
    """사용자가 전화번호를 두 번 말하면 모델도 같은 것으로 인식해야 한다."""
    v = TokenVault()
    assert v.token_for("s1", "phone", PHONE) == v.token_for("s1", "phone", PHONE)


def test_different_values_get_different_tokens():
    v = TokenVault()
    assert v.token_for("s1", "phone", PHONE) != v.token_for("s1", "rrn", RRN)


def test_sessions_are_isolated():
    """A의 토큰으로 B의 값을 꺼낼 수 없어야 한다."""
    v = TokenVault()
    token = v.token_for("alice", "rrn", RRN)
    restored, n = v.restore("bob", f"당신의 번호는 {token} 입니다")
    assert n == 0 and RRN not in restored


def test_restore_round_trip():
    v = TokenVault()
    token = v.token_for("s1", "rrn", RRN)
    restored, n = v.restore("s1", f"확인된 번호는 {token} 입니다")
    assert n == 1 and restored == f"확인된 번호는 {RRN} 입니다"


def test_unknown_token_is_left_alone():
    v = TokenVault()
    v.token_for("s1", "rrn", RRN)
    out, n = v.restore("s1", "[PII:rrn:999]")
    assert out == "[PII:rrn:999]" and n == 0


def test_expired_session_is_purged():
    v = TokenVault(ttl=0.0)
    v.token_for("s1", "rrn", RRN)
    assert v.session_count == 0


def test_capacity_is_bounded():
    """세션이 무한히 쌓이면 볼트 자체가 취약점이 된다."""
    v = TokenVault(max_sessions=3)
    for i in range(10):
        v.token_for(f"s{i}", "phone", PHONE)
    assert v.session_count <= 3


# ---------- 세션 키 ----------

def test_session_comes_from_session_id():
    assert session_of(body("hi", "eval-abc"), "fallback") == "eval-abc"


def test_falls_back_to_request_id_without_session_id():
    """sessionId가 없으면 요청 단위로 격리한다. 남의 토큰이 섞이는 것보다 낫다."""
    assert session_of(body("hi", None), "req-1") == "req-1"
    assert session_of(b"not json", "req-1") == "req-1"


# ---------- 마스킹 검사기 ----------

@pytest.fixture
def masker():
    return PIIDetector("mask")


def insp(b: bytes, rid: str = "r1") -> Inspection:
    return Inspection(request_id=rid, method="POST", path="/chat", headers={}, body=b)


@pytest.mark.anyio
async def test_masking_returns_transform(masker):
    v = await masker.inspect(insp(body(f"주민등록번호 {RRN}입니다")))
    assert v.action is Action.TRANSFORM
    assert v.meta["masked"] == 1


@pytest.mark.anyio
async def test_original_value_is_gone_from_body(masker):
    v = await masker.inspect(insp(body(f"주민등록번호 {RRN}이고 연락처는 {PHONE}입니다")))
    out = v.body.decode()
    assert RRN not in out and PHONE not in out
    assert "[PII:rrn:1]" in out and "[PII:phone:2]" in out


@pytest.mark.anyio
async def test_masked_body_is_still_valid_json(masker):
    """타겟이 파싱할 수 있어야 한다. 토큰이 JSON을 깨뜨리면 안 된다."""
    v = await masker.inspect(insp(body(f"카드 4111-1111-1111-1111 결제")))
    assert json.loads(v.body)["mode"] == "query"


@pytest.mark.anyio
async def test_no_pii_means_no_transform(masker):
    """PII가 없으면 본문을 건드리지 않는다. 4-A의 투명성이 유지된다."""
    v = await masker.inspect(insp(body("표준 근무시간이 몇 시부터인가요?")))
    assert v.action is Action.ALLOW and v.body is None


@pytest.mark.anyio
async def test_masking_is_reversible_within_session(masker):
    """4-F에서 쓸 복원 경로가 실제로 성립하는지 지금 확인해둔다."""
    original = body(f"연락처 {PHONE}입니다", "eval-9")
    v = await masker.inspect(insp(original))
    restored, n = masker.vault.restore("eval-9", v.body.decode())
    assert n == 1 and restored == original.decode()


@pytest.mark.anyio
async def test_meta_never_contains_the_raw_value(masker):
    """D-029: 감사 로그로 나가는 정보에 원문이 섞이면 안 된다."""
    v = await masker.inspect(insp(body(f"주민등록번호 {RRN}, 연락처 {PHONE}")))
    blob = str(v.meta) + v.reason
    assert RRN not in blob and PHONE not in blob


@pytest.mark.anyio
async def test_repeated_value_in_one_message_shares_a_token(masker):
    v = await masker.inspect(insp(body(f"{PHONE} 또는 {PHONE} 로 연락주세요")))
    assert v.body.decode().count("[PII:phone:1]") == 2


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------- 회귀: 모델이 대괄호를 잃어버린 토큰도 복원한다 ----------
# 2026-08-07 실측(P-109): gemma3:4b가 "인사팀([PII:phone:1])으로"를 받아
# "인사팀(PII:phone:1)으로"로 다시 써서 대괄호를 잃었다. 65건 중 4건.
# 복원에 실패해 내부 토큰이 사용자 응답에 그대로 노출됐다 → EVAL 3.2 '부분 저하'.

@pytest.mark.parametrize("template", [
    "자세한 내용은 인사팀({t})으로 문의해 주세요.",       # 대괄호 유실 + 모델이 괄호를 붙임
    "연락처 {t} 로 회신 드립니다.",                        # 대괄호 유실, 맨몸
    "문의: [{t}]",                                         # 대괄호 유실 후 다시 대괄호
])
def test_restores_even_when_model_drops_brackets(template):
    v = TokenVault()
    token = v.token_for("s1", "phone", PHONE)
    core = token[1:-1]                                     # "PII:phone:1"
    text = template.format(t=core)
    restored, n = v.restore("s1", text)
    assert n == 1
    assert PHONE in restored
    assert "PII:" not in restored


def test_model_added_parentheses_are_preserved():
    """모델이 붙인 괄호까지 먹어버리면 문장이 어색해진다. 핵심만 치환한다."""
    v = TokenVault()
    token = v.token_for("s1", "phone", PHONE)
    out, _ = v.restore("s1", f"인사팀({token[1:-1]})으로 문의")
    assert out == f"인사팀({PHONE})으로 문의"


def test_residual_tokens_detects_leftovers():
    """복원 못 한 토큰이 남으면 개수를 셀 수 있어야 감사 로그로 감시할 수 있다."""
    v = TokenVault()
    assert v.residual_tokens("연락처 PII:phone:99 입니다") == 1
    assert v.residual_tokens("연락처 010-1234-5678 입니다") == 0


@pytest.mark.anyio
async def test_response_hook_reports_residual(masker):
    """알 수 없는 토큰이 응답에 있으면 residual_tokens로 보고한다."""
    out = await masker.on_response("nosuch-session", "인사팀(PII:phone:1)으로")
    assert out is not None
    _, meta = out
    assert meta["restored"] == 0 and meta["residual_tokens"] == 1
