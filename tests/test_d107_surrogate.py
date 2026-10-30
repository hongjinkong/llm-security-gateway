"""D-107 B: 모양 보존 대체값. B1(모양)·B2(관대한 복원)·B3(국제 전화 탐지). 데이터는 전부 합성이다."""
from __future__ import annotations

import json

import pytest

from gateway import surrogate
from gateway.detectors.patterns import digits, find_all, luhn_ok, rrn_date_ok
from gateway.vault import TokenVault

SAMPLES = {
    "phone": ["010-2345-6789", "02-123-4567", "031.234.5678", "010 2345 6789", "+82 10 2345 6789", "+82-10-2345-6789",
              "+1 415 555 2671", "(02) 123-4567", "(031) 234-5678", "+821023456789", "010\n2345\n6789", "010\t2345\t6789"],
    "card": ["4111-1111-1111-1111", "4111 1111 1111 1111", "5500000000000004", "3400-000000-00009"],
    "rrn": ["900101-1234563", "900101 1234563", "9001011234563", "050101-3123456"],
    "email": ["kim@example.com", "j.hong@hanbit-tech.example", "KIM_99+tag@Mail.Example.COM"],
    "secret": ["sk-" + "A1b2C3d4" * 6, "sk-proj-" + "A1b2C3d4" * 6, "AKIA" + "ABCDEFGHIJKLMNOP", "ghp_" + "x1" * 18,
               "github_pat_" + "A1" * 12, "AIza" + "B2" * 17 + "c", "xoxb-" + "1234567890-abc",
               "eyJ" + "a1" * 6 + ".eyJ" + "b2" * 6 + "." + "c3" * 6,
               "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq\nhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----",
               "-----BEGIN RSA PRIVATE KEY-----\\nMIIEvQIBADANBgkq\\nhkiG\\n-----END RSA PRIVATE KEY-----"],   # 옛 경로의 이스케이프 꼴
}


# ---------- B1 모양 ----------

@pytest.mark.parametrize("kind, value", [(k, v) for k, vs in SAMPLES.items() for v in vs])
def test_b1_surrogate_keeps_the_shape_and_redetects_as_its_own_kind(kind, value):
    for _ in range(20):                                   # 난수라 여러 번
        s = surrogate.make(kind, value)
        assert s != value
        found = find_all(s)
        assert len(found) == 1 and found[0].kind == kind and (found[0].start, found[0].end) == (0, len(s)), (value, s)
        if kind in ("phone", "card", "rrn"):
            assert len(digits(s)) == len(digits(value))
        if kind == "card":
            assert luhn_ok(digits(s))
        if kind == "rrn":
            d = digits(s)
            assert rrn_date_ok(d[:2], d[2:4], d[4:6], d[6]) and d[6] in "1234"
        if kind == "phone":
            if value.startswith("+"):
                assert s.startswith(value.split()[0][:3])  # 국가번호 유지
            else:
                assert digits(s)[:2] == digits(value)[:2]  # 국내 접두사 유지
            assert "\n" not in s and "\t" not in s        # 줄바꿈·탭 구분자는 빈칸으로(JSON 응답에서 다시 걸리게)
        if kind == "email":
            assert s.rsplit(".", 1)[1] == value.rsplit(".", 1)[1] and s.count("@") == 1 and s.rsplit(".", 1)[0].islower()
        if kind == "secret":
            for prefix in ("sk-proj-", "sk-", "AKIA", "ghp_", "github_pat_", "AIza", "xoxb-", "eyJ", "-----BEGIN"):
                if value.startswith(prefix):
                    assert s.startswith(prefix)
            if value.startswith("eyJ"):
                assert s.split(".")[1].startswith("eyJ") and [len(p) for p in s.split(".")] == [len(p) for p in value.split(".")]
            if value.startswith("-----BEGIN"):
                assert s.endswith(value[value.index("-----END"):]) and s.count("\n") == value.count("\n")
                assert "MIIEvQIBADANBgkq" not in s


def test_b1_same_value_same_surrogate_different_values_differ():
    v = TokenVault()
    a = v.token_for("r", "phone", "010-2345-6789")
    b = v.token_for("r", "phone", "010-2345-6789")
    c = v.token_for("r", "phone", "010-9876-5432")
    assert a == b != c


def test_b1_surrogate_never_collides_with_values_already_in_the_request():
    """요청 안의 다른 원문·다른 대체값과 숫자열이 같으면 다시 뽑는다."""
    v = TokenVault()
    originals = [f"010-{i:04d}-{i:04d}" for i in range(50)]
    sur = [v.token_for("r", "phone", o) for o in originals]
    keys = [digits(s) for s in sur]
    assert len(set(keys)) == len(keys) and not set(keys) & {digits(o) for o in originals}


# ---------- B2 관대한 복원 ----------

@pytest.mark.parametrize("rewrite", [lambda s: s, lambda s: s.replace("-", " "), lambda s: s.replace("-", ""),
                                     lambda s: s.replace("-", "."), lambda s: f"({s[:3]}) {s[4:]}"],
                         ids=["same", "spaces", "none", "dots", "parens"])
def test_b2_phone_restores_whatever_separator_the_model_uses(rewrite):
    v = TokenVault()
    s = v.token_for("r", "phone", "010-2345-6789")
    out, n = v.restore("r", f"연락처는 {rewrite(s)} 입니다")
    assert n == 1 and out == "연락처는 010-2345-6789 입니다"


def test_b2_json_response_text_restores_with_escaping():
    v = TokenVault()
    s = v.token_for("r", "phone", "010\n2345\n6789")
    text = json.dumps({"choices": [{"message": {"content": f"번호 {s} 끝"}}]}, ensure_ascii=False)
    out, n = v.restore("r", text, lambda x: json.dumps(x, ensure_ascii=False)[1:-1])
    assert n == 1 and json.loads(out)["choices"][0]["message"]["content"] == "번호 010\n2345\n6789 끝"


def test_b2_pem_restores_from_json_response_text():
    """PEM 대체값은 줄바꿈이 있어 JSON 텍스트에서는 `\\n` 두 글자가 된다 — 그래도 되찾는다."""
    v = TokenVault()
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq\nhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"
    s = v.token_for("r", "secret", pem)
    text = json.dumps({"content": f"키 {s} 확인"}, ensure_ascii=False)
    out, n = v.restore("r", text, lambda x: json.dumps(x, ensure_ascii=False)[1:-1])
    assert n == 1 and json.loads(out)["content"] == f"키 {pem} 확인"


def test_b2_values_the_model_invents_are_left_alone():
    v = TokenVault()
    v.token_for("r", "phone", "010-2345-6789")
    out, n = v.restore("r", "010-1111-2222 는 제 번호가 아닙니다")
    assert n == 0 and "010-1111-2222" in out


# ---------- B3 국제 전화 탐지 ----------

@pytest.mark.parametrize("text", ["+82-10-2345-6789", "+82 10 2345 6789", "+1 415 555 2671", "(02) 123-4567",
                                  "(031) 234-5678", "+821023456789", "+44 20 7946 0958", "+49 30 1234567"])
def test_b3_international_and_parenthesized_numbers_are_detected(text):
    found = find_all(f"번호 {text} 입니다")
    assert [f.kind for f in found] == ["phone"] and f"번호 {text} 입니다"[found[0].start:found[0].end] == text


@pytest.mark.parametrize("text", ["+1 2 3", "v1.2.3", "2026-10-30", "+1234", "1+1=2", "x+82 10 2345 6789",
                                  "+1234567890123456"])
def test_b3_short_long_or_glued_sequences_are_not_phones(text):
    assert not [f for f in find_all(text) if f.kind == "phone"]
