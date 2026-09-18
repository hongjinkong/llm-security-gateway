"""6단계 검증: 카나리 관측 검사기 — `CANARY_DESIGN` 4-4의 변이 검사 5종을 고정한다.

**이 파일은 `gateway/detectors/canary.py`보다 먼저 쓰였다.** 코드가 없는 시점에
테스트를 먼저 두는 이유는 설계 동결과 같다 — 구현을 보고 나서 "무엇을 지킬지"를
정하면, 구현이 이미 하고 있는 일을 요구사항으로 되받아쓰게 된다.

이 프로젝트는 통과 여부가 아니라 **변이 검사**로 테스트의 유효성을 확인한다(D-055).
아래 표의 5종은 각각 **일부러 깨뜨렸을 때 반드시 실패해야 하는** 항목이다.

    1  관측형은 응답을 바꾸지 않는다   on_response가 카나리를 지우게 바꾸면 실패
    2  값이 없으면 기동 실패           prepare()의 검사를 지우면 실패
    3  meta에 토큰 값이 없다           meta에 검출 문자열을 넣으면 실패
    4  세 종류를 구분한다              정규식 하나로 뭉뚱그리면 실패
    5  소스에 카나리 리터럴이 없다     상수로 박으면 실패

여기에 설계에 없던 보강 하나를 더했다(2026-08-21, 사용자 승인) —
**세 값이 서로 겹치면 기동 실패.** 근거는 2번(R3)과 같다.

**1번이 이 설계의 핵심이다.** 관측형과 차단형의 거리는 `return text` 한 줄이고,
그 한 줄을 바꿔도 감사 로그는 여전히 `"restore"`라고 찍힌다. 그러면 D-059의 FP
바닥값이 조용히 0이 되고, *"방어가 자기가 재는 신호를 지운다"*(D-058 1절 근거 B)가
아무 경고 없이 성립한다. 코드가 그걸 막아야 한다.

**카나리 실제 값은 이 파일에 없다.** 가짜 토큰을 주입해서 쓴다(EVAL 2.3b / R2).
"""
from __future__ import annotations

import json
import pathlib

import httpx
import pytest

import gateway
from gateway.chain import DetectorChain
from gateway.detectors.base import Action, Inspection
from gateway.detectors.canary import (CanaryCollisionError, CanaryMissingError,
                                      CanaryObserveDetector, CanaryWiringError,
                                      validate_canary_position)
from gateway.version import canary_fingerprint

# --- 가짜 토큰 --------------------------------------------------------------
#
# **접두사를 일부러 공유시킨다.** 실제 세 토큰은 형식이 같아서(설계 2절 마지막 줄)
# 종류를 구분하려면 값이 필요하다. 가짜 토큰을 서로 전혀 다르게 만들면 그 함정이
# 재현되지 않는다 — test_pii.py가 L-005에서 "한글에 붙여 써야 재현된다"고 적어둔
# 것과 같은 실수다. 접두사만 보고 세면 여기서 걸린다.
FAKE_PREFIX = "ZZTEST-0000-"
FAKE_A = FAKE_PREFIX + "aaaa1111"
FAKE_B = FAKE_PREFIX + "bbbb2222"
FAKE_DOC = FAKE_PREFIX + "dddd3333"

# 실제 카나리의 **형식 접두사**다. 값이 아니라 형식이며 `eval/canary_fpr.py`의
# 정규식에도 그대로 있다. 변이 5번은 이 문자열이 gateway/ 소스에 없음을 요구한다.
CANARY_PREFIX = "WS-2026-"


def make_detector(a: str | None = FAKE_A, b: str | None = FAKE_B,
                  doc: str | None = FAKE_DOC) -> CanaryObserveDetector:
    return CanaryObserveDetector(a, b, doc)


def insp(body: bytes = b'{"message":"hello"}') -> Inspection:
    return Inspection(request_id="r1", method="POST", path="/api/v1/workspace/x/chat",
                      headers={}, body=body, session="s1")


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ==========================================================================
# 변이 1. 관측형은 응답을 바꾸지 않는다  ← 6단계의 유일한 약속
# ==========================================================================

@pytest.mark.anyio
async def test_on_response_returns_the_very_same_object():
    """**이 테스트가 6단계의 핵심이다.**

    설계 4-2: *"반환 텍스트는 입력과 동일한 객체여야 한다."*
    `gateway/main.py`가 `restored != text`일 때만 본문을 교체하므로, 같은 값을
    돌려주면 응답 바이트가 보존된다. `==`이 아니라 `is`로 고정하는 이유는
    "우연히 같은 문자열을 새로 만들어 돌려주는" 구현까지 배제하기 위해서다.
    """
    det = make_detector()
    text = f"답변입니다. {FAKE_A} 그리고 {FAKE_B} 또 {FAKE_DOC}"
    out = await det.on_response("s1", text)
    assert out is not None, "카나리가 셋 다 있는데 아무것도 기록하지 않았다"
    assert out[0] is text, "응답 텍스트가 새 객체다 — 관측형이 응답을 건드렸다"


@pytest.mark.anyio
async def test_on_response_preserves_every_token_occurrence():
    """`is` 비교와 별개로 **개수 보존**을 따로 고정한다.

    지우기·재작성뿐 아니라 "하나만 남기고 합치기" 같은 변형도 여기서 걸린다.
    """
    det = make_detector()
    text = f"{FAKE_A} x {FAKE_A} y {FAKE_B} z {FAKE_DOC}"
    out = await det.on_response("s1", text)
    assert out is not None
    restored = out[0]
    for tok, n in ((FAKE_A, 2), (FAKE_B, 1), (FAKE_DOC, 1)):
        assert restored.count(tok) == n, f"{tok!r}의 등장 횟수가 {n}에서 변했다"
    assert len(restored) == len(text)


@pytest.mark.anyio
async def test_chain_run_response_leaves_text_untouched():
    """체인을 통과해도 텍스트가 그대로여야 한다. step은 1개 남는다."""
    text = f"사내 규정 안내 {FAKE_DOC} 입니다"
    out, steps = await DetectorChain([make_detector()]).run_response("s1", text)
    assert out is text
    assert [s.detector for s in steps] == ["canary_observe"]
    assert steps[0].action == "restore"


@pytest.mark.anyio
async def test_inspect_never_touches_the_request():
    """요청 경로에서는 아무것도 하지 않는다(설계 4-2).

    요청에 카나리가 들어 있어도 판정은 ALLOW이고, body를 만들지 않으며,
    meta도 남기지 않는다. 요청 경로에 meta를 남기면 `Inspection.prior`를 통해
    뒤 검사기가 그걸 보고 판단할 수 있게 되고(D-053의 실제 전례), 관측형이
    조용히 다른 층의 입력이 된다.
    """
    det = make_detector()
    body = json.dumps({"message": f"이 코드 {FAKE_DOC} 알려줘"}).encode()
    v = await det.inspect(insp(body))
    assert v.action is Action.ALLOW
    assert v.body is None
    assert v.detector == "canary_observe"
    assert v.meta == {}, "요청 경로에서 meta를 남겼다 — prior로 새어 나간다"


def test_detector_name_says_it_is_observe_only():
    """이름만 보고 관측형임을 알아야 `verify_gateway.sh`의 활성 검사기 줄이
    제 역할을 한다(설계 4-1, `injection_similarity_observe` 선례)."""
    assert make_detector().name == "canary_observe"


# ==========================================================================
# 변이 2. 값이 없으면 기동 실패 (R3 / D-043 / D-048)
# ==========================================================================

@pytest.mark.anyio
@pytest.mark.parametrize("a,b,doc,missing", [
    (None, FAKE_B, FAKE_DOC, "canary_a"),
    (FAKE_A, None, FAKE_DOC, "canary_b"),
    (FAKE_A, FAKE_B, None, "canary_doc"),
    ("", FAKE_B, FAKE_DOC, "canary_a"),          # 빈 문자열도 "없음"이다
    (None, None, None, "canary_a"),
])
async def test_prepare_fails_loud_when_a_value_is_missing(a, b, doc, missing):
    """값이 안 넘어온 채 관측이 돌면 검출률이 조용히 0이 되고,
    *"관측했는데 아무것도 안 나왔다"*는 거짓 기록이 남는다(설계 3-1 R3).

    예외 문구에 **어느 값이 비었는지**는 들어가되 **값 자체는 안 들어간다.**

    **타입을 `CanaryMissingError`로 지정한다**(2026-08-21). `RuntimeError`로 받으면
    중복값 분기가 이 분기를 가려준다 — 세 값이 전부 None인 케이스는 값 존재 검사를
    없애도 중복값 검사에 걸려 RuntimeError가 나고, 그러면 이 테스트가 통과한다.
    변이 검사 M2가 실제로 그 구멍을 드러냈다.
    """
    with pytest.raises(CanaryMissingError) as e:
        await make_detector(a, b, doc).prepare()
    assert missing in str(e.value)
    for tok in (FAKE_A, FAKE_B, FAKE_DOC):
        assert tok not in str(e.value), "예외 문구에 토큰 값이 들어갔다"


@pytest.mark.anyio
async def test_prepare_succeeds_when_all_three_are_present():
    """**양성대조.** 이게 없으면 `prepare()`가 무조건 raise하는 구현도 위 테스트를
    전부 통과한다. "안 걸린다"만 검사하면 아무것도 안 지킨다(이 저장소의 반복 교훈)."""
    await make_detector().prepare()   # 예외가 없으면 통과


@pytest.mark.anyio
@pytest.mark.parametrize("a,b,doc,pair", [
    (FAKE_A, FAKE_A, FAKE_DOC, ("canary_a", "canary_b")),
    (FAKE_A, FAKE_B, FAKE_A, ("canary_a", "canary_doc")),
    (FAKE_A, FAKE_DOC, FAKE_DOC, ("canary_b", "canary_doc")),
])
async def test_prepare_rejects_values_that_collide(a, b, doc, pair):
    """**설계 4-2에 없는 보강이다**(2026-08-21, 사용자 승인).

    값이 겹치면 같은 등장을 두 칸에 각각 세게 되어 EVAL 2.5가 요구한 종류별
    분리 집계가 조용히 무의미해진다. 관측은 돌고 숫자도 나오므로 겉으로는
    정상이고, V1의 지문 대조도 세 값을 묶어 해싱하므로 이 경우를 못 잡는다.
    근거는 R3와 같다 — 조용히 틀린 숫자를 내는 상태보다 기동 실패가 낫다.

    타입을 `CanaryCollisionError`로 지정하는 이유는 위 테스트와 같다 — 두 분기가
    서로를 가려주면 안 된다.
    """
    with pytest.raises(CanaryCollisionError) as e:
        await make_detector(a, b, doc).prepare()
    msg = str(e.value)
    for kind in pair:
        assert kind in msg
    for tok in (FAKE_A, FAKE_B, FAKE_DOC):
        assert tok not in msg, "예외 문구에 토큰 값이 들어갔다"


# ==========================================================================
# 변이 3. meta에 토큰 값이 없다 (R4 / D-029)
# ==========================================================================

@pytest.mark.anyio
async def test_meta_has_exactly_the_three_count_keys():
    det = make_detector()
    out = await det.on_response("s1", f"{FAKE_A} {FAKE_B} {FAKE_DOC}")
    assert out is not None
    meta = out[1]
    assert set(meta) == {"canary_a", "canary_b", "canary_doc"}
    assert meta == {"canary_a": 1, "canary_b": 1, "canary_doc": 1}


@pytest.mark.anyio
async def test_meta_values_are_plain_integers():
    """위치·주변 텍스트·매치 문자열을 담으면 여기서 걸린다.
    감사 로그가 유출 경로가 되는 것을 막는다(설계 4-3)."""
    det = make_detector()
    out = await det.on_response("s1", f"앞뒤 문맥 {FAKE_DOC} 뒤 문맥")
    assert out is not None
    for k, v in out[1].items():
        assert type(v) is int, f"{k}가 정수가 아니다: {v!r}"


@pytest.mark.anyio
async def test_meta_never_contains_the_token_value():
    """D-029 (1): 로그로 나가는 정보에 원문이 섞이면 안 된다."""
    det = make_detector()
    out = await det.on_response("s1", f"{FAKE_A} {FAKE_B} {FAKE_DOC}")
    assert out is not None
    blob = str(out[1])
    for tok in (FAKE_A, FAKE_B, FAKE_DOC):
        assert tok not in blob
    assert FAKE_PREFIX not in blob, "접두사만 담아도 유출이다"


@pytest.mark.anyio
async def test_returns_none_when_nothing_was_detected():
    """전부 0이면 None. 감사 로그의 `response_detectors`가 0건 줄로 불어나지
    않게 한다(설계 4-3)."""
    det = make_detector()
    assert await det.on_response("s1", "연차휴가는 연 15일입니다.") is None


@pytest.mark.anyio
async def test_chain_records_no_step_when_nothing_detected():
    out, steps = await DetectorChain([make_detector()]).run_response(
        "s1", "연차휴가는 연 15일입니다.")
    assert out is not None and steps == []


# ==========================================================================
# 변이 4. 세 종류를 구분한다 (EVAL 2.5 종류별 분리 기록)
# ==========================================================================

@pytest.mark.anyio
async def test_counts_are_separated_by_kind():
    """A 2회 / B 1회 / DOC 0회. 정규식 하나로 뭉뚱그리면 합계 3이 한 칸에 몰린다."""
    det = make_detector()
    out = await det.on_response("s1", f"{FAKE_A} ... {FAKE_B} ... {FAKE_A}")
    assert out is not None
    assert out[1] == {"canary_a": 2, "canary_b": 1, "canary_doc": 0}


@pytest.mark.anyio
@pytest.mark.parametrize("tok,key", [
    (FAKE_A, "canary_a"), (FAKE_B, "canary_b"), (FAKE_DOC, "canary_doc")])
async def test_one_kind_alone_lights_only_its_own_counter(tok, key):
    det = make_detector()
    out = await det.on_response("s1", f"응답 본문 {tok} 끝")
    assert out is not None
    expected = {"canary_a": 0, "canary_b": 0, "canary_doc": 0} | {key: 1}
    assert out[1] == expected


@pytest.mark.anyio
async def test_shared_prefix_does_not_confuse_the_kinds():
    """**실제 세 토큰은 접두사가 같다**(설계 2절). 접두사나 형식 패턴으로 세면
    여기서 걸린다 — 그것이 D-058이 후보 (f)를 기각한 사유다."""
    det = make_detector()
    out = await det.on_response("s1", f"{FAKE_PREFIX}zzzz9999 그리고 {FAKE_DOC}")
    assert out is not None
    assert out[1] == {"canary_a": 0, "canary_b": 0, "canary_doc": 1}, (
        "형식이 같은 남의 문자열을 카나리로 셌다")


# ==========================================================================
# 체인 위치 — 목록 맨 뒤 = 응답 경로 맨 앞 = 타겟 원본
#
# **설계 4-1에 없는 보강이다**(2026-08-21, 사용자 승인).
# 설계는 이 위치를 권고 이유로 적었지 위반 시 기동 실패로 적지 않았다.
#
# 지금은 위치를 틀려도 숫자가 안 바뀐다 — 응답 경로에서 텍스트를 바꾸는 검사기가
# `pii_mask`의 볼트 복원 하나뿐이고 카나리는 볼트에 없다. 그래서 이 규칙은
# 오늘의 숫자가 아니라 **D-059가 차단형·출력 재작성을 여는 시점**을 지킨다.
# 규칙이 필요해지는 시점과 규칙을 잊기 쉬운 시점이 같아서 코드에 박는다.
# ==========================================================================

def test_position_rule_accepts_canary_at_the_end():
    """**양성대조를 겸한다.** 무조건 raise하는 구현을 배제한다."""
    validate_canary_position(["injection_rule", "pii_mask", "canary_observe"])
    validate_canary_position(["canary_observe"])
    validate_canary_position(["injection_rule", "pii_mask"])   # 없으면 볼 것도 없다
    validate_canary_position([])


@pytest.mark.parametrize("names", [
    ["canary_observe", "pii_mask"],
    ["injection_rule", "canary_observe", "pii_mask"],
])
def test_position_rule_rejects_canary_before_another_detector(names):
    with pytest.raises(CanaryWiringError) as e:
        validate_canary_position(names)
    assert "canary_observe" in str(e.value)


# ==========================================================================
# 변이 5. 소스에 카나리 리터럴이 없다 (R2 / EVAL 2.3b)
# ==========================================================================

def test_gateway_source_has_no_canary_literal():
    """`gateway/` 패키지의 모든 .py에 카나리 형식 접두사가 없어야 한다.

    canary.py 한 파일만 보지 않는 이유: 값이 다른 파일로 새면 그것도 하드코딩이다.
    2026-08-21 시점 실측으로 gateway/ 전체에 이 문자열이 없다.
    """
    root = pathlib.Path(gateway.__file__).resolve().parent
    offenders = [
        p.relative_to(root).as_posix()
        for p in sorted(root.rglob("*.py"))
        if "__pycache__" not in p.parts
        and CANARY_PREFIX in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"소스에 카나리 리터럴이 박혔다: {offenders}"


# ==========================================================================
# 지문 — 값이 아니라 지문을 세 곳에서 대조한다 (R5 / 설계 3-2)
# ==========================================================================

def test_fingerprint_is_stable_and_distinguishes_values():
    assert canary_fingerprint(FAKE_A) == canary_fingerprint(FAKE_A)
    assert canary_fingerprint(FAKE_A) != canary_fingerprint(FAKE_B)
    assert canary_fingerprint(FAKE_A) != canary_fingerprint(FAKE_DOC)
    assert len(canary_fingerprint(FAKE_A)) == 8


def test_fingerprint_survives_a_shared_prefix():
    """실제 세 토큰은 접두사가 같다. 지문이 접두사만 반영하면 대조가 무의미해진다."""
    assert canary_fingerprint(FAKE_PREFIX + "aaaa1111") != \
        canary_fingerprint(FAKE_PREFIX + "aaaa1112")


# ==========================================================================
# 통합 — 게이트웨이를 실제로 띄워서 확인한다
#
# 여기가 V2(영점 검사, `CANARY_DESIGN` 5-2)의 코드판이다.
# "관측형이다"는 주장이 단위 테스트가 아니라 **실제 응답 바이트**로 증명돼야 한다.
#
# 스텁 타겟이 요청 message를 textResponse에 그대로 되싣는다(tests/stub_target.py).
# 그래서 스텁을 고치지 않고도 "응답에 카나리가 실려 나오는 상황"을 만들 수 있다.
# ==========================================================================

CANARY_ENV = {
    "GATEWAY_DETECTORS": "canary_observe",
    "GATEWAY_CANARY_A": FAKE_A,
    "GATEWAY_CANARY_B": FAKE_B,
    "GATEWAY_CANARY_DOC": FAKE_DOC,
}

PAYLOAD = {
    "message": f"안내문 {FAKE_A} / {FAKE_A} / {FAKE_B} / {FAKE_DOC}",
    "mode": "query",
    "sessionId": "canary-it-0001",
}
CHAT_PATH = "/api/v1/workspace/hr/chat"


@pytest.fixture(scope="module")
def canary_stack(make_stack):
    return make_stack(**CANARY_ENV)


def test_gateway_response_is_byte_identical_to_the_target(canary_stack):
    """**V2 영점 검사의 코드판.**

    같은 요청을 타겟에 직접 / 게이트웨이 경유로 보내 응답 바이트를 비교한다.
    한 바이트라도 다르면 관측형이 아니다.
    """
    direct = httpx.post(canary_stack.target + CHAT_PATH, json=PAYLOAD, timeout=10)
    through = httpx.post(canary_stack.gateway + CHAT_PATH, json=PAYLOAD, timeout=10)
    assert direct.status_code == through.status_code == 200
    assert through.json()["textResponse"] == direct.json()["textResponse"]
    assert through.content == direct.content, "게이트웨이가 응답 바이트를 바꿨다"


def test_canary_tokens_survive_the_gateway(canary_stack):
    """지웠는지만이 아니라 **몇 개가 남았는지**까지 본다."""
    r = httpx.post(canary_stack.gateway + CHAT_PATH, json=PAYLOAD, timeout=10)
    body = r.json()["textResponse"]
    assert body.count(FAKE_A) == 2
    assert body.count(FAKE_B) == 1
    assert body.count(FAKE_DOC) == 1


def test_audit_log_records_counts_and_no_values(canary_stack):
    """감사 로그에 종류별 횟수는 남고 토큰 값은 안 남는다(R4 / D-029)."""
    httpx.post(canary_stack.gateway + CHAT_PATH, json=PAYLOAD, timeout=10)
    lines = [x for x in canary_stack.log_lines() if x.get("path") == CHAT_PATH]
    assert lines, "감사 로그에 요청이 안 남았다"
    last = lines[-1]

    assert last["blocked"] is False
    assert last["transformed"] is False, "요청 경로에서 본문을 바꿨다"

    steps = [s for s in last["response_detectors"] if s["detector"] == "canary_observe"]
    assert len(steps) == 1
    step = steps[0]
    assert step["action"] == "restore"

    # **(4,2,2)는 관측 범위가 "응답 본문 전체"라는 결정의 결과다**
    # (2026-08-21, 사용자 승인). 스텁은 요청 message를 textResponse와
    # echo.body.message 두 곳에 실으므로 본문 전체에서는 정확히 두 배가 된다.
    #
    # 이 기대값은 처음에 (2,1,1)로 박혀 있었다. 그때 나는 "카나리가 사용자
    # 응답에 몇 번 나오나"를 textResponse 기준으로 **암묵 가정**했고, 그 가정은
    # 설계 어디에도 없었다. 스텁의 echo 필드가 그 가정을 드러냈다.
    #
    # 숫자를 결과에 맞춰 고친 것이 아니라 **범위를 결정하고 그 결정을 적은
    # 것이다.** 아래 양성대조가 두 범위가 실제로 다른 값을 낸다는 것을 고정한다 —
    # 그게 없으면 이 (4,2,2)는 아무것도 안 지킨다.
    assert (step["canary_a"], step["canary_b"], step["canary_doc"]) == (4, 2, 2)

    raw = canary_stack.log_path.read_text(encoding="utf-8")
    for tok in (FAKE_A, FAKE_B, FAKE_DOC):
        assert tok not in raw, "감사 로그에 카나리 값이 남았다"
    assert FAKE_PREFIX not in raw


def test_gateway_does_not_start_without_a_canary_value(make_stack):
    """배선은 됐는데 값이 없으면 **기동 자체가 실패한다**(R3).

    `chain.prepare()`가 lifespan에서 불리므로 예외가 그대로 기동 실패가 된다 —
    `injection_similarity`가 T 없이, `injection_judge`가 ACK 없이 안 뜨는 것과
    같은 장치다(D-048 / D-054).

    값을 빼는 대신 **빈 문자열**을 넘긴다. 맥북 `.env`에는 `GATEWAY_CANARY_*`가
    없지만, 그 사실에 기대면 나중에 환경이 달라졌을 때 이 테스트가 조용히
    의미를 잃는다.
    """
    with pytest.raises(RuntimeError):
        make_stack(**{**CANARY_ENV, "GATEWAY_CANARY_DOC": ""})


def test_health_reports_fingerprints_and_never_values(canary_stack):
    """health가 **게이트웨이가 읽은 값의 지문**을 보고한다(R5).

    verify_gateway.sh가 이 값을 `.env` 지문·마지막 setup 지문과 대조한다.
    지문이 틀리면 대조가 통과해도 아무것도 안 지킨 것이 되므로, 값이 아니라
    **정확히 그 값의 지문**인지까지 본다.
    """
    r = httpx.get(canary_stack.gateway + "/__gateway/health", timeout=10)
    fp = r.json()["canary_fp"]
    assert fp == {
        "canary_a": canary_fingerprint(FAKE_A),
        "canary_b": canary_fingerprint(FAKE_B),
        "canary_doc": canary_fingerprint(FAKE_DOC),
    }
    for tok in (FAKE_A, FAKE_B, FAKE_DOC):
        assert tok not in r.text, "health가 카나리 값을 노출했다"
    assert FAKE_PREFIX not in r.text


def test_the_two_counting_scopes_really_differ(canary_stack):
    """**양성대조.** 관측 범위 선택이 실제로 숫자를 바꾼다는 것을 고정한다.

    두 범위가 우연히 같은 값을 내는 응답으로 검사하면, 나중에 구현이 조용히
    `textResponse`만 세도 위 테스트가 안 걸린다. "안 걸린다"만 검사하면
    아무것도 안 지킨다 — test_pii.py의 `test_raw_decode_would_have_missed_it`과
    같은 자리다.

    두 범위의 차이는 그 자체로 기록이다. 게이트웨이 관측값과 garak 리포트를
    나란히 놓을 수 없는 이유가 여기 있고, 설계 5-2의 V3가 "대조 불가"로
    처리되는 근거다.
    """
    r = httpx.post(canary_stack.gateway + CHAT_PATH, json=PAYLOAD, timeout=10)
    only_text = r.json()["textResponse"]
    whole_body = r.text

    def counts(s: str) -> tuple[int, int, int]:
        return s.count(FAKE_A), s.count(FAKE_B), s.count(FAKE_DOC)

    assert counts(only_text) == (2, 1, 1), "textResponse 범위"
    assert counts(whole_body) == (4, 2, 2), "본문 전체 범위"
    assert counts(only_text) != counts(whole_body), (
        "두 범위가 같은 값을 낸다 — 이 응답으로는 범위 결정을 시험할 수 없다")


def test_gateway_does_not_start_when_canary_is_not_last(make_stack):
    """위치 규칙도 **기동 실패**로 걸린다. 로그 경고가 아니다.

    측정 도구의 표시 버그는 사람에게 경고를 무시하는 법을 가르친다(D-053).
    """
    with pytest.raises(RuntimeError):
        make_stack(**{**CANARY_ENV, "GATEWAY_DETECTORS": "canary_observe,pii_mask"})
