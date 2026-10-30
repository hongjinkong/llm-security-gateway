"""D-111: 결정적 대체값. 번호 R1~R5는 D-111 §4의 표와 같다(R3은 test_d107_surrogate의 모양 규칙이 그대로 지킨다)."""
from __future__ import annotations

import json

import httpx
import pytest

import gateway.vault as vault_mod
from gateway.vault import TokenVault

CHAT = "/v1/chat/completions"
KEY = b"k" * 32
VALUES = [("phone", "010-2345-6789"), ("phone", "+82 10-2345-6789"), ("email", "j.hong@hanbit-tech.example"),
          ("card", "4111-1111-1111-1111"), ("rrn", "900101-1234563"), ("secret", "sk-proj-" + "A1b2C3d4" * 6)]


def received(stack) -> list[str]:
    return httpx.get(f"{stack.target}/__stub/received").json()["bodies"]


# ---------- R1 ----------

@pytest.mark.parametrize("kind, value", VALUES)
def test_r1_same_key_and_value_give_the_same_surrogate_in_every_request(kind, value):
    first = TokenVault(key=KEY).token_for("r0", kind, value)
    assert first != value
    assert {TokenVault(key=KEY).token_for(f"r{i}", kind, value) for i in range(100)} == {first}   # 요청·볼트가 달라도
    assert TokenVault(key=b"x" * 32).token_for("r0", kind, value) != first


def test_r1_vault_without_a_key_is_deterministic_only_within_itself():
    v = TokenVault()
    assert v.token_for("a", "phone", "010-2345-6789") == v.token_for("b", "phone", "010-2345-6789")


# ---------- R2 ----------

def test_r2_forced_overlap_is_split_by_the_counter(monkeypatch):
    real, calls = vault_mod.surrogate.make, []

    def overlapping(kind, value, rng=None):
        calls.append(value)
        return "010-1111-2222" if len(calls) <= 2 else real(kind, value, rng)   # 두 원문의 첫 시도를 같은 값으로

    monkeypatch.setattr(vault_mod.surrogate, "make", overlapping)
    v = TokenVault(key=KEY)
    a, b = v.token_for("r", "phone", "010-2345-6789"), v.token_for("r", "phone", "010-9876-5432")
    assert a == "010-1111-2222" and b != a and len(calls) == 3
    assert v.restore("r", f"{a} {b}") == ("010-2345-6789 010-9876-5432", 2)


def test_r2_many_values_in_one_request_never_share_a_surrogate():
    v = TokenVault(key=KEY)
    tokens = [v.token_for("r", "phone", f"010-{1000 + i // 10000:04d}-{i % 10000:04d}") for i in range(5000)]
    assert len(set(tokens)) == 5000


# ---------- R4 ----------

@pytest.fixture(scope="module")
def masked(make_stack):
    return make_stack(GATEWAY_DETECTORS="pii_mask")


def test_r4_second_turn_history_has_the_same_bytes_as_the_first_turn(masked):
    user1 = {"role": "user", "content": "제 번호는 010-2345-6789이고 메일은 j.hong@hanbit-tech.example입니다. 연차 규정을 알려 주세요"}
    r1 = httpx.post(masked.gateway + CHAT, json={"model": "stub-model", "messages": [user1]})
    raw1 = received(masked)[-1]
    sent1 = json.loads(raw1)["messages"]
    answer = r1.json()["choices"][0]["message"]                       # 사용자가 받은(복원된) 답
    assert "010-2345-6789" in answer["content"]
    httpx.post(masked.gateway + CHAT, json={"model": "stub-model", "messages": [user1, answer, {"role": "user", "content": "고마워요"}]})
    raw2 = received(masked)[-1]
    sent2 = json.loads(raw2)["messages"]
    piece = json.dumps(sent1[0], ensure_ascii=False)
    assert piece in raw1 and piece in raw2, "턴 2 이력의 user 메시지 바이트가 턴 1과 다르다"
    assert sent2[1]["content"] == "[stub] " + sent1[0]["content"]    # 턴 1에 상류가 낸 답(대체값 포함) 그대로
    assert "010-2345-6789" not in raw2


# ---------- R5 ----------

@pytest.mark.parametrize("key", ["", "short-key"])
def test_r5_mask_mode_needs_a_long_enough_key(make_stack, key):
    with pytest.raises(RuntimeError, match="기동 실패"):
        make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_SURROGATE_KEY=key)


def test_r5_detect_mode_boots_without_a_key(make_stack):
    assert make_stack(GATEWAY_DETECTORS="pii", GATEWAY_SURROGATE_KEY="").info()["detectors"] == ["pii"]
