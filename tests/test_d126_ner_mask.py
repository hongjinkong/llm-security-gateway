"""D-126(PLAN 17-1단계): 이름·주소 가림 — 탐지 사이드카의 NER 종류(person·address·org)를 정책에서 켠다. 번호 H1~H9는 D-126 §4의 표와 같다.

HTTP 경로는 시험용 사이드카(tests/stub_detect.py — 규칙, onnxruntime 없음) 앞에서, 검사기 단위는 가짜 클라이언트(FakeDetect)로 본다. 데이터는 전부 합성이다.
"""
from __future__ import annotations

import json
import random
import re

import httpx
import pytest

from gateway import surrogate
from gateway.api.base import ApiError
from gateway.detect_client import MAX_CHARS, OVERLAP, DetectUnavailable, Span, windows
from gateway.detectors.base import Action, Inspection
from gateway.detectors.patterns import NER_KINDS
from gateway.detectors.pii import ALL_KINDS, DETECT_ONLY, REGEX_KINDS, PIIDetector
from gateway.messages import t
from gateway.settings import Settings
from gateway.vault import TokenVault, norm_key
from tests.conftest import ADMIN, free_port, start, stop
from tests.stub_detect import app as detect_app
from tests.test_streaming import content_of

CHAT, MESSAGES, RESPONSES = "/v1/chat/completions", "/v1/messages", "/v1/responses"
NAME, ADDRESS, PHONE, ORG = "김철수", "서울특별시 강남구 테헤란로 152", "010-2345-6789", "한빛소프트"
TEXT = f"고객 {NAME} 님의 주소는 {ADDRESS}이고 번호는 {PHONE}입니다. {ORG} 재직"
KINDS = ",".join(ALL_KINDS)          # 정규식 12 + person·address·org
KEY = b"k" * 32


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def sidecar():
    port = free_port()
    server = start(detect_app, port)
    yield f"http://127.0.0.1:{port}"
    stop([server])


def calls(sidecar: str) -> list[int]:
    return httpx.get(sidecar + "/__stub/calls").json()["calls"]


@pytest.fixture(scope="module")
def ner(make_stack, sidecar):
    """가림 정책 + 이름·주소·직장(org는 기본 감사만), 실패 closed(기본)."""
    return make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_KINDS=KINDS, GATEWAY_DETECT_URL=sidecar)


@pytest.fixture(scope="module")
def ner_open(make_stack, sidecar):
    return make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_KINDS=KINDS, GATEWAY_DETECT_URL=sidecar, GATEWAY_DETECT_FAIL="open",
                      GATEWAY_DETECT_TIMEOUT="0.5")


@pytest.fixture(scope="module")
def ner_quick(make_stack, sidecar):
    return make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_KINDS=KINDS, GATEWAY_DETECT_URL=sidecar, GATEWAY_DETECT_TIMEOUT="0.5")


@pytest.fixture(scope="module")
def ner_detect(make_stack, sidecar):
    return make_stack(GATEWAY_DETECTORS="pii", GATEWAY_PII_KINDS=KINDS, GATEWAY_DETECT_URL=sidecar)


@pytest.fixture(scope="module")
def ner_refused(make_stack):
    return make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_KINDS=KINDS, GATEWAY_DETECT_URL=f"http://127.0.0.1:{free_port()}")


def received(stack) -> list[str]:
    return httpx.get(f"{stack.target}/__stub/received").json()["bodies"]


def audit(stack, r: httpx.Response) -> dict:
    (line,) = [x for x in stack.log_lines() if x["request_id"] == r.headers["X-Gateway-Request-Id"]]
    return line


def pii_step(stack, r: httpx.Response) -> dict:
    return next(d for d in audit(stack, r)["detectors"] if d["detector"] in ("pii_mask", "pii"))


def chat(content: str, model: str = "stub-model", **extra) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": content}], **extra}


def insp(text: str) -> Inspection:
    body = json.dumps(chat(text, "m"), ensure_ascii=False).encode()
    return Inspection(request_id="r", method="POST", path=CHAT, headers={}, body=body, session="s")


class FakeDetect:
    """사이드카 대신 — 텍스트마다 정해진 구간을 돌려주거나 실패한다."""

    def __init__(self, spans: dict[str, list[tuple[str, int, int]]] | None = None, error: str | None = None) -> None:
        self.by_text, self.error, self.calls = spans or {}, error, 0

    async def prepare(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def spans(self, texts: list[str]) -> list[list[Span]]:
        self.calls += 1
        if self.error:
            raise DetectUnavailable(self.error)
        return [[Span(k, s, e, 0.97) for k, s, e in self.by_text.get(text, [])] for text in texts]


# ---------- H1 종류·설정 ----------

def test_h1_defaults_keep_ner_off_and_the_config_accepts_the_new_kinds():
    assert len(ALL_KINDS) == 15 and set(NER_KINDS) <= set(ALL_KINDS) and len(REGEX_KINDS) == 12 and "org" in DETECT_ONLY
    s = Settings.from_env({})
    assert s.pii_kinds == REGEX_KINDS and (s.detect_url, s.detect_timeout, s.detect_fail) == ("", 10.0, "closed")
    s = Settings.from_env({"GATEWAY_PII_KINDS": "phone,person,Address", "GATEWAY_DETECT_URL": "http://detect:8081/",
                           "GATEWAY_DETECT_TIMEOUT": "2.5", "GATEWAY_DETECT_FAIL": " Open "})
    assert s.pii_kinds == ("phone", "person", "address") and (s.detect_url, s.detect_timeout, s.detect_fail) == ("http://detect:8081", 2.5, "open")
    for env in ({"GATEWAY_DETECT_FAIL": "maybe"}, {"GATEWAY_PII_KINDS": "name"}, {"GATEWAY_PII_DETECT_KINDS": "people"}):
        with pytest.raises(ValueError):
            Settings.from_env(env)
    with pytest.raises(ValueError):
        PIIDetector("mask", detect_fail="half")


def test_h1_ner_kinds_without_a_sidecar_url_refuse_to_start(make_stack, tmp_path):
    with pytest.raises(RuntimeError, match="기동 실패"):
        make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_PII_KINDS="phone,person")
    config = tmp_path / "gateway.toml"
    config.write_text('[policies.names]\npii_kinds = ["phone", "address"]\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="기동 실패"):                  # 설정 파일의 정책이 켠 경우도
        make_stack(GATEWAY_DETECTORS="pii_mask", GATEWAY_CONFIG=str(config))
    assert make_stack(GATEWAY_DETECTORS="", GATEWAY_PII="off", GATEWAY_PII_KINDS="person").info()["detect"] is None   # off면 종류는 뜻이 없다
    assert "GATEWAY_DETECT_URL" in t("no_detect_url", "en", policies="default") and "person" in t("no_detect_url", "ko", policies="default")


def test_h1_info_shows_the_sidecar_and_the_default_stack_does_not_call_it(ner, stack, sidecar):
    assert ner.info()["detect"] == sidecar and stack.info()["detect"] is None
    before = calls(sidecar)
    httpx.post(stack.gateway + CHAT, json=chat(TEXT))
    assert calls(sidecar) == before


# ---------- H2 가림 ----------

def test_h2_names_and_addresses_go_upstream_as_fakes_and_come_back(ner):
    r = httpx.post(ner.gateway + CHAT, json=chat(TEXT))
    assert r.status_code == 200, r.text
    sent = json.loads(received(ner)[-1])["messages"][0]["content"]
    assert NAME not in sent and ADDRESS not in sent and PHONE not in sent and ORG in sent        # org는 기본 감사만
    assert sent.startswith("고객 ") and " 님의 주소는 서울특별시 강남구 " in sent and sent.endswith(f"입니다. {ORG} 재직")   # 머리 토큰·나머지 글 그대로
    assert r.json()["choices"][0]["message"]["content"] == "[stub] " + TEXT
    line, step = audit(ner, r), pii_step(ner, r)
    assert step["pii"] == {"person": 1, "address": 1, "phone": 1} and step["unmasked"] == {"org": 1} and step["ner_ms"] >= 0
    assert (line["pii_issued"], line["pii_restored"], line["pii_suspect"]) == (3, 3, 0) and r.headers["x-gateway-pii"] == "issued=3 restored=3"


def test_h2_messages_and_responses_apis_restore_too(ner):
    r = httpx.post(ner.gateway + MESSAGES, json={"model": "stub-model", "max_tokens": 10, "messages": [{"role": "user", "content": TEXT}]})
    assert r.status_code == 200 and r.json()["content"][0]["text"] == "[stub] " + TEXT and NAME not in received(ner)[-1]
    r = httpx.post(ner.gateway + RESPONSES, json={"model": "stub-model", "input": TEXT})
    (msg,) = [o for o in r.json()["output"] if o["type"] == "message"]
    assert msg["content"][0]["text"] == "[stub] " + TEXT and NAME not in received(ner)[-1] and ADDRESS not in received(ner)[-1]


def test_h2_a_surrogate_name_is_never_the_original_and_is_deterministic(ner):
    sent = []
    for _ in range(2):
        httpx.post(ner.gateway + CHAT, json=chat(f"{NAME} 님에게 전달"))
        sent.append(json.loads(received(ner)[-1])["messages"][0]["content"])
    assert sent[0] == sent[1] and NAME not in sent[0]
    fake = sent[0].split()[0]
    assert len(fake) == 3 and surrogate.final_class(fake[-1]) == surrogate.final_class(NAME[-1])


# ---------- H3 스트림 ----------

def test_h3_streams_restore_names_and_addresses_across_chunk_boundaries(ner):
    with httpx.stream("POST", ner.gateway + CHAT, json=chat(TEXT, "stub-stream", stream=True), timeout=30) as r:
        body = r.read()
    assert content_of(body) == "[stub] " + TEXT
    with httpx.stream("POST", ner.gateway + MESSAGES, json={"model": "stub-stream", "max_tokens": 50, "stream": True,
                                                            "messages": [{"role": "user", "content": TEXT}]}, timeout=30) as r:
        events = [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ")]
    text = "".join(e["delta"]["text"] for e in events if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta")
    assert text == "[stub] " + TEXT


# ---------- H4 둘째 턴·캐시 ----------

def test_h4_second_turn_history_is_byte_identical_and_served_from_the_cache(ner, sidecar):
    user1 = {"role": "user", "content": f"{NAME} 고객의 주소 {ADDRESS}로 보내 주세요"}
    r1 = httpx.post(ner.gateway + CHAT, json={"model": "stub-model", "messages": [user1]})
    raw1 = received(ner)[-1]
    sent1 = json.loads(raw1)["messages"]
    answer = r1.json()["choices"][0]["message"]
    assert NAME in answer["content"] and ADDRESS in answer["content"]
    before = calls(sidecar)
    httpx.post(ner.gateway + CHAT, json={"model": "stub-model", "messages": [user1, answer, {"role": "user", "content": "고마워요"}]})
    raw2 = received(ner)[-1]
    sent2 = json.loads(raw2)["messages"]
    assert json.dumps(sent1[0], ensure_ascii=False) in raw1 and json.dumps(sent1[0], ensure_ascii=False) in raw2   # 이력 바이트가 같다
    assert sent2[1]["content"] == "[stub] " + sent1[0]["content"]           # 턴 1에 상류가 낸 답(대체값 포함) 그대로
    assert NAME not in raw2 and ADDRESS not in raw2
    assert calls(sidecar)[len(before):] == [2]                               # user1은 캐시에서 — 답과 새 질문 둘만 한 요청으로 갔다


# ---------- H5 대체값 ----------

@pytest.mark.parametrize("name", ["김민준", "이수아", "박하늘", "최철", "민준", "남궁민수", "정은"])
def test_h5_korean_name_surrogates_keep_length_and_final_sound_class(name):
    for seed in range(30):
        s = surrogate.make("person", name, random.Random(seed))
        assert s != name and len(s) == max(3, len(name)) and re.fullmatch(r"[가-힣]+", s), (name, s)
        assert surrogate.final_class(s[-1]) == surrogate.final_class(name[-1]) and s[0] in dict(surrogate.SURNAMES)


def test_h5_latin_and_other_script_names():
    s = surrogate.make("person", "Sarah Kim", random.Random(1))
    assert s != "Sarah Kim" and len(s.split()) == 2 and s.split()[-1] in surrogate.EN_LAST
    assert surrogate.make("person", "JOHN", random.Random(1)).isupper() and " " not in surrogate.make("person", "John", random.Random(1))
    s = surrogate.make("person", "山田太郎", random.Random(1))
    assert len(s) == 3 and re.fullmatch(r"[가-힣]+", s)


@pytest.mark.parametrize("value, head", [
    ("서울특별시 강남구 테헤란로 152", "서울특별시 강남구 "), ("경기 성남시 분당구 판교역로 235, 7층", "경기 성남시 분당구 "),
    ("대전 유성구 봉명동 783-16", "대전 유성구 "), ("인천광역시 부평구 경원대로 422 25층 2501호", "인천광역시 부평구 "),
    ("목포시 백년대로59길 334", "목포시 "), ("서울 송파구 잠실동 래미안아파트 103동 1204호", "서울 송파구 "),
])
def test_h5_address_surrogates_keep_the_head_and_the_digit_shape(value, head):
    first_body = value.split()[len(head.split())]
    for seed in range(10):
        s = surrogate.make("address", value, random.Random(seed))
        assert s != value and s.startswith(head) and first_body not in s, (value, s)
        assert [len(x) for x in re.findall(r"\d+", s)] == [len(x) for x in re.findall(r"\d+", value)]
        assert [x[-1] for x in re.findall(r"\d+", s)] == [x[-1] for x in re.findall(r"\d+", value)]      # 마지막 자리 — 조사가 맞는다
        assert s.endswith(value[-1]) if not value[-1].isdigit() else True                                 # '층'·'호' 같은 꼬리


def test_h5_org_surrogates_keep_known_prefixes_and_tails():
    cases = {"삼성전자": ("", "전자"), "(주)한빛소프트": ("(주)", ""), "주식회사 나래로지스": ("주식회사 ", ""), "서울대학교병원": ("", "대학교병원"),
             "한결회계법인": ("", "회계법인"), "제일정밀(주)": ("", "(주)"), "Contoso Ltd.": ("", " Ltd."), "Northwind Traders": ("", " Traders")}
    for value, (prefix, tail) in cases.items():
        s = surrogate.make("org", value, random.Random(2))
        assert s != value and s.startswith(prefix) and s.endswith(tail) and len(s) > len(prefix) + len(tail), (value, s)


@pytest.mark.parametrize("kind, value", [("person", NAME), ("address", ADDRESS), ("org", ORG)])
def test_h5_string_surrogates_are_deterministic_per_key(kind, value):
    first = TokenVault(key=KEY).token_for("a", kind, value)
    assert {TokenVault(key=KEY).token_for(f"r{i}", kind, value) for i in range(20)} == {first} != {value}
    assert TokenVault(key=b"x" * 32).token_for("a", kind, value) != first


# ---------- H6 겹침·규칙 ----------

@pytest.mark.anyio
async def test_h6_regex_wins_over_an_overlapping_ner_span_and_an_address_needs_a_digit():
    text = f"번호 {PHONE} 서울 날씨와 {ADDRESS} 근처"
    i, a, b = text.index(PHONE), text.index("서울 날씨"), text.index(ADDRESS)
    fake = FakeDetect({text: [("org", i, i + len(PHONE)), ("address", a, a + 2), ("address", b, b + len(ADDRESS))]})
    det = PIIDetector("mask", kinds=ALL_KINDS, vault=TokenVault(key=KEY), detect=fake, detect_kinds=())     # org도 가리는 설정 — 겹침이 버린다
    v = await det.inspect(insp(text))
    assert v.action is Action.TRANSFORM and v.meta["pii"] == {"phone": 1, "address": 1} and v.meta["unmasked"] == {"address": 1}
    found = [(f["kind"], f["start"], f.get("mask", True)) for f in v.meta["findings"]]
    assert found == [("phone", i, True), ("address", a, False), ("address", b, True)]
    out = json.loads(v.body)["messages"][0]["content"]
    assert "서울 날씨와" in out and ADDRESS not in out and PHONE not in out


@pytest.mark.anyio
async def test_h6_org_is_audit_only_by_default_and_masked_when_removed_from_detect_kinds():
    text = f"{ORG} 재직"
    fake = FakeDetect({text: [("org", 0, len(ORG))]})
    v = await PIIDetector("mask", kinds=ALL_KINDS, vault=TokenVault(key=KEY), detect=fake).inspect(insp(text))
    assert v.action is Action.ALLOW and v.meta["unmasked"] == {"org": 1} and v.meta["pii"] == {}
    v = await PIIDetector("mask", kinds=ALL_KINDS, vault=TokenVault(key=KEY), detect=fake, detect_kinds=()).inspect(insp(text))
    assert v.action is Action.TRANSFORM and ORG not in v.body.decode() and v.meta["pii"] == {"org": 1}


@pytest.mark.anyio
async def test_h6_kinds_not_enabled_are_dropped_and_no_ner_kind_means_no_sidecar_call():
    text = f"{NAME} {ADDRESS}"
    fake = FakeDetect({text: [("person", 0, 3), ("address", 4, 4 + len(ADDRESS))]})
    v = await PIIDetector("mask", kinds=REGEX_KINDS + ("address",), vault=TokenVault(key=KEY), detect=fake).inspect(insp(text))
    assert v.meta["pii"] == {"address": 1} and fake.calls == 1
    det = PIIDetector("mask", kinds=REGEX_KINDS, vault=TokenVault(key=KEY), detect=fake)
    assert det.detect is None and (await det.inspect(insp(text))).action is Action.ALLOW and fake.calls == 1


# ---------- H7 실패 동작 ----------

@pytest.mark.parametrize("marker", ["@@500@@", "@@garbage@@"])
def test_h7_sidecar_failure_is_503_without_upstream_when_closed(ner, marker):
    before = len(received(ner))
    r = httpx.post(ner.gateway + CHAT, json=chat(f"{marker} {NAME} {PHONE}"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "detect_unavailable" and r.headers["retry-after"] == "1"
    assert len(received(ner)) == before
    line = audit(ner, r)
    assert line["error"] == "detect_unavailable" and line["upstream_ms"] is None and line["status"] == 503
    r = httpx.post(ner.gateway + MESSAGES, json={"model": "stub-model", "max_tokens": 10, "messages": [{"role": "user", "content": f"{marker} {NAME}"}]})
    assert r.status_code == 503 and r.json() == {"type": "error", "error": {"type": "overloaded_error", "message": "name/address detection is unavailable"}}


def test_h7_timeout_and_connection_refused_are_503_when_closed(ner_quick, ner_refused):
    r = httpx.post(ner_quick.gateway + CHAT, json=chat(f"@@sleep@@ {NAME}"), timeout=30)
    assert r.status_code == 503 and audit(ner_quick, r)["error"] == "detect_unavailable"
    r = httpx.post(ner_refused.gateway + CHAT, json=chat(NAME))
    assert r.status_code == 503 and audit(ner_refused, r)["error"] == "detect_unavailable"
    r = httpx.post(ner_refused.gateway + CHAT, json=chat("이름이 없는 문장"))       # 사이드카가 없어도 — 가릴 것이 있는지는 사이드카만 안다
    assert r.status_code == 503


def test_h7_open_masks_regex_kinds_and_records_the_error(ner_open):
    r = httpx.post(ner_open.gateway + CHAT, json=chat(f"@@500@@ {NAME} {PHONE}"))
    sent = json.loads(received(ner_open)[-1])["messages"][0]["content"]
    assert r.status_code == 200 and PHONE not in sent and NAME in sent
    step = pii_step(ner_open, r)
    assert step["ner_error"] == "http_500" and step["pii"] == {"phone": 1} and audit(ner_open, r)["error"] is None
    r = httpx.post(ner_open.gateway + CHAT, json=chat(f"@@sleep@@ {NAME}"), timeout=30)
    assert r.status_code == 200 and pii_step(ner_open, r)["ner_error"] == "timeout" and pii_step(ner_open, r)["action"] == "allow"


def test_h7_detect_policy_always_passes_and_counts_ner_kinds(ner_detect):
    r = httpx.post(ner_detect.gateway + CHAT, json=chat(f"@@500@@ {NAME}"))
    assert r.status_code == 200 and pii_step(ner_detect, r)["ner_error"] == "http_500"
    r = httpx.post(ner_detect.gateway + CHAT, json=chat(TEXT))
    assert r.status_code == 200 and NAME in received(ner_detect)[-1]
    assert pii_step(ner_detect, r)["pii"] == {"person": 1, "address": 1, "phone": 1, "org": 1}
    assert audit(ner_detect, r)["transformed"] is False


@pytest.mark.anyio
async def test_h7_closed_raises_only_when_a_masked_ner_kind_is_on():
    with pytest.raises(ApiError) as e:
        await PIIDetector("mask", kinds=ALL_KINDS, vault=TokenVault(key=KEY), detect=FakeDetect(error="connect")).inspect(insp(TEXT))
    assert (e.value.status, e.value.code) == (503, "detect_unavailable")
    v = await PIIDetector("mask", kinds=REGEX_KINDS + ("org",), vault=TokenVault(key=KEY), detect=FakeDetect(error="connect")).inspect(insp(TEXT))
    assert v.action is Action.TRANSFORM and v.meta["ner_error"] == "connect" and v.meta["pii"] == {"phone": 1}      # 감사만 종류뿐 — 통과
    v = await PIIDetector("mask", kinds=ALL_KINDS, vault=TokenVault(key=KEY), detect=FakeDetect(error="timeout"), detect_fail="open").inspect(insp(TEXT))
    assert v.action is Action.TRANSFORM and v.meta["ner_error"] == "timeout" and v.meta["pii"] == {"phone": 1}


# ---------- H8 긴 텍스트·상한 ----------

def test_h8_windows_cover_each_position_exactly_once():
    for n in (0, 1, MAX_CHARS, MAX_CHARS + 1, 2 * MAX_CHARS - OVERLAP, 2 * MAX_CHARS, 50_000):
        ws = windows(n)
        assert ws[0][2] == 0 and ws[-1][3] == n and all(b - a <= MAX_CHARS and a <= oa <= ob <= b for a, b, oa, ob in ws)
        for (a, b, oa, ob), nxt in zip(ws, ws[1:]):
            assert ob == nxt[2] and b - ob == OVERLAP // 2 and nxt[2] - nxt[0] == OVERLAP // 2


def test_h8_long_text_is_windowed_and_each_name_is_masked_once_in_place(ner, sidecar):
    text = "가" * 11_800 + f" {NAME} 님과 " + "나" * 91 + " 이영희 님 " + "다" * 200
    assert len(text) > MAX_CHARS and text.index(NAME) == 11_801 and text.index("이영희") == 11_900     # 첫 창이 가진 자리·둘째 창이 가진 자리(둘 다 겹친 구간)
    before = calls(sidecar)
    r = httpx.post(ner.gateway + CHAT, json=chat(text, "stub-quiet"), timeout=60)
    assert r.status_code == 200, r.text
    sent = json.loads(received(ner)[-1])["messages"][0]["content"]
    assert len(sent) == len(text) and NAME not in sent and "이영희" not in sent
    assert sent[:11_801] == text[:11_801] and sent[11_804:11_900] == text[11_804:11_900] and sent[11_903:] == text[11_903:]
    assert pii_step(ner, r)["pii"] == {"person": 2} and calls(sidecar)[len(before):] == [1, 1]


@pytest.mark.anyio
async def test_h8_ner_findings_count_toward_the_findings_cap():
    text = "김철수 이영희 박민준"
    fake = FakeDetect({text: [("person", 0, 3), ("person", 4, 7), ("person", 8, 11)]})
    with pytest.raises(ApiError) as e:
        await PIIDetector("mask", kinds=ALL_KINDS, vault=TokenVault(key=KEY), detect=fake, max_findings=2).inspect(insp(text))
    assert (e.value.status, e.value.code) == (413, "too_many_findings")


# ---------- H9 볼트 ----------

def test_h9_string_surrogates_restore_with_whitespace_variants_and_json_escapes():
    v = TokenVault(key=KEY)
    name, addr = v.token_for("s", "person", NAME), v.token_for("s", "address", ADDRESS)
    assert v.restore("s", f"안녕하세요 {name}님, {addr}로 보냅니다") == (f"안녕하세요 {NAME}님, {ADDRESS}로 보냅니다", 2)
    assert v.restore("s", re.sub(r"\s+", "  ", addr))[0] == ADDRESS and v.restore("s", addr.replace(" ", "\\n"))[0] == ADDRESS   # JSON 인자 채널
    assert v.restore("s", "박" + name) == ("박" + name, 0)                           # 앞이 한글 음절이면 이름이 아니다
    assert v.residual("s", f"{name} 남음") == 1 and v.residual("s", "없음") == 0 and v.suspect("s", f"{addr}") == 1
    latin = v.token_for("s", "person", "Sarah Kim")
    assert v.restore("s", latin.upper()) == ("Sarah Kim", 1)                       # 대소문자 무시


def test_h9_regex_kind_wins_when_a_string_surrogate_overlaps():
    v = TokenVault(key=KEY)
    p = v.token_for("s", "phone", PHONE)
    entry = v._sessions["s"]
    entry.ner.append((p, "org"))                                                   # 같은 글자열을 직장 대체값으로도 등록(억지 겹침)
    entry.ner_kind[norm_key("org", p)], entry.by_key[norm_key("org", p)] = "org", "ORG"
    assert v.restore("s", f"번호 {p}") == (f"번호 {PHONE}", 1)


def test_h9_hold_keeps_korean_tails_with_spaces():
    v = TokenVault(key=KEY)
    name, addr = v.token_for("s", "person", NAME), v.token_for("s", "address", ADDRESS)
    assert v.hold("s", "주소는 " + addr[:9]) == 9 and v.hold("s", "주소는 " + addr[:6]) == 6    # '서울특별시 강남구' · '서울특별시 ' — 공백을 뺀 꼬리로 본다
    assert v.hold("s", "담당 " + name[:2]) == 2 and v.hold("s", "날씨 좋다") == 0 and v.hold("s", "주소는 서울특별시강남") == 7
    assert v.hold("s", "값 " + addr) == 0                                             # 완성된 대체값은 보류하지 않는다(복원 뒤의 텍스트다)


def test_h9_avoid_skips_a_surrogate_already_present_in_the_request():
    first = TokenVault(key=KEY).token_for("a", "person", NAME)
    v = TokenVault(key=KEY)
    second = v.token_for("b", "person", NAME, avoid=f"회의에 {first} 씨도 옵니다")
    assert second != first and v.restore("b", second) == (NAME, 1)
    assert TokenVault(key=KEY).token_for("c", "phone", PHONE, avoid="010") == TokenVault(key=KEY).token_for("d", "phone", PHONE)   # 정규식 종류는 보지 않는다


# ---------- 리뷰 + 반박 검증 뒤 더한 것(D-126 §6) ----------

def test_h7_closed_503_audit_line_keeps_the_sidecar_reason(ner):
    """closed 503 줄에도 검사기 항목(ner_error·ner_ms)이 남는다 — 체인이 끝나지 않으므로 relay가 ApiError.meta로 한 단계짜리 결과를 만든다."""
    r = httpx.post(ner.gateway + CHAT, json=chat(f"@@500@@ {NAME}"))
    (step,) = audit(ner, r)["detectors"]
    assert r.status_code == 503 and (step["detector"], step["action"], step["reason"], step["ner_error"]) == ("pii_mask", "reject", "detect_unavailable", "http_500")
    assert "ner_ms" in step and NAME not in json.dumps(step, ensure_ascii=False)


def test_h7_open_failures_are_counted_in_stats_and_metrics(ner_open):
    httpx.post(ner_open.gateway + CHAT, json=chat(f"@@500@@ {NAME} {PHONE}"))
    st = httpx.get(ner_open.gateway + "/__gateway/stats", headers=ADMIN).json()
    assert st["detect_errors"]["http_500"] >= 1 and st["recent"][0]["ner_error"] == "http_500"
    assert 'gateway_detect_errors_total{reason="http_500"}' in httpx.get(ner_open.gateway + "/__gateway/metrics", headers=ADMIN).text


def test_h1_timeout_and_url_are_validated_at_start():
    for env in ({"GATEWAY_DETECT_TIMEOUT": "0"}, {"GATEWAY_DETECT_TIMEOUT": "-1"}, {"GATEWAY_DETECT_TIMEOUT": "nan"}, {"GATEWAY_DETECT_TIMEOUT": "10s"},
                {"GATEWAY_DETECT_URL": "detect:8081"}, {"GATEWAY_DETECT_URL": "http://detect:8081/v1/detect"}, {"GATEWAY_DETECT_URL": "http://detect:8081?x=1"},
                {"GATEWAY_DETECT_URL": "ftp://detect:8081"}):
        with pytest.raises(ValueError):
            Settings.from_env(env)
    assert Settings.from_env({"GATEWAY_DETECT_URL": "https://detect:8081/", "GATEWAY_DETECT_TIMEOUT": "0.5"}).detect_url == "https://detect:8081"
    assert "GATEWAY_DETECT_TIMEOUT" in t("positive", "en", var="GATEWAY_DETECT_TIMEOUT", value="0")


def test_h9_latin_surrogates_match_whole_words_only_and_any_ascii_case():
    """'dilemma' 속 'emma'를 이름으로 되돌리지 않는다(앞뒤가 영숫자가 아닐 때만). 대소문자는 ASCII만 무시한다 — 터키어 ı·İ는 다른 글자다."""
    v = TokenVault(key=KEY)
    name = v.token_for("s", "person", "John")
    assert v.restore("s", f"x{name}y {name.upper()} {name}1 {name.lower()}.") == (f"x{name}y John {name}1 John.", 2)
    from gateway.vault import _literal, norm_key as nk
    assert re.search(_literal("Daniel"), "DANIEL") and not re.search(_literal("Daniel"), "Danıel") and not re.search(_literal("Daniel"), "DANİEL")
    entry = v._sessions["s"]
    entry.ner.append(("Daniel", "person"))                                              # 억지로 등록한 대체값 — 변형 글자가 와도 KeyError가 아니라 그대로 둔다
    entry.ner_kind[nk("person", "Daniel")], entry.by_key[nk("person", "Daniel")], entry.ner_re = "person", "Tom", None
    assert v.restore("s", "Danıel DANIEL") == ("Danıel Tom", 1)


def test_h9_hold_keeps_digit_led_surrogates_and_streams_restore_them():
    from gateway.streaming import ChatShape, StreamRestorer
    from tests.test_streaming import sse
    v = TokenVault(key=KEY)
    token = v.token_for("s", "address", "101동 1203호")
    assert token[0].isdigit() and v.hold("s", "주소는 " + token[:4]) == 4 and v.hold("s", "주소는 " + token[:7]) == 7
    text = f"주소는 {token} 입니다."
    for size in (1, 2, 3, 5):
        restorer = StreamRestorer(ChatShape(), lambda t, escape=None: v.restore("s", t, escape), lambda t: v.hold("s", t))
        out = restorer.feed(sse([text[i:i + size] for i in range(0, len(text), size)])) + restorer.finish()
        assert content_of(out) == "주소는 101동 1203호 입니다.", size


@pytest.mark.parametrize("value, leak", [
    ("서울시강남구테헤란로152", "테헤란로"), ("서울특별시 강남구 테헤란로123", "테헤란로"), ("서울특별시 강남구 역삼1동 737-32", "역삼"),
    ("서울 강남구 삼성아파트101동 1203호", "삼성"), ("서울 강남구 래미안2차 101동", "래미안"), ("서울시 서초구 서초대로 301 삼성빌딩3층", "삼성"),
    ("서울특별시 종로구 세종대로 209 (세종로)", "세종"), ("대구 수성구 수성로275번길91", "수성로"),
])
def test_h5_glued_address_tokens_do_not_leak_hangul(value, leak):
    for seed in range(5):
        s = surrogate.make("address", value, random.Random(seed))
        assert leak not in s and s != value, (value, s)
        assert [len(x) for x in re.findall(r"\d+", s)] == [len(x) for x in re.findall(r"\d+", value)]
        assert [x[-1] for x in re.findall(r"\d+", s)] == [x[-1] for x in re.findall(r"\d+", value)]
        assert s.count("(") == value.count("(") and s.count(")") == value.count(")")
        for unit in ("동", "호", "층", "번길", "차"):
            assert s.count(unit) >= value.count(unit) - value.count(leak) * leak.count(unit), (value, s, unit)   # 단위 낱말은 그대로
    assert surrogate.make("address", "서울특별시 강남구 역삼1동 737-32", random.Random(1)).startswith("서울특별시 강남구 ")
    assert surrogate.make("address", "서울시강남구테헤란로152", random.Random(1)).startswith("서울시강남구")


def test_h5_mixed_script_org_stems_do_not_leak_hangul():
    for value, leak in (("SK하이닉스", "하이닉스"), ("삼성SDS", "삼성"), ("카카오M", "카카오"), ("7번가피자", "번가피자"), ("(주)SK텔레콤", "텔레콤")):
        s = surrogate.make("org", value, random.Random(3))
        assert leak not in s and s != value, (value, s)
    assert surrogate.make("org", "(주)SK텔레콤", random.Random(3)).startswith("(주)")


def test_h9_thousands_of_string_surrogates_restore_quickly():
    """5,000건을 발급한 세션의 복원이 수십 ms다 — 대안마다 단언을 두던 정규식은 컴파일만 3초였다(D-126 §6 리뷰)."""
    import time
    v = TokenVault(key=KEY)
    r = random.Random(5)
    names = {"".join(r.choice(surrogate.GIVEN_ANY) for _ in range(3)) for _ in range(6000)}
    tokens = [v.token_for("s", "person", n) for n in sorted(names)[:5000]]
    text = ("참석자: " + " ".join(tokens[:50]) + " 입니다. ") * 20            # 1,000개, 약 5KB
    t0 = time.perf_counter()
    restored, n = v.restore("s", text)
    residual, suspect = v.leftovers("s", restored)
    assert n == 1000 and residual == 0 and time.perf_counter() - t0 < 1.0
    assert all(tok not in restored for tok in tokens[:50])


# ---------- 검증자가 메운 빈자리(설정 파일로 켠 정책·Responses 스트림·도구 인자·캐시 밀어내기·묶음 상한) ----------

NAMES_KEY, PLAIN_KEY = "gw-names-synthetic-0123", "gw-plain-synthetic-4567"


@pytest.fixture(scope="module")
def cfg(make_stack, sidecar, tmp_path_factory):
    from gateway.settings import key_hash
    toml = (f'[[clients]]\nname = "names-app"\nkey_sha256 = "{key_hash(NAMES_KEY)}"\npolicy = "names"\n\n'
            f'[[clients]]\nname = "plain-app"\nkey_sha256 = "{key_hash(PLAIN_KEY)}"\n\n[policies.default]\npii_mode = "mask"\n\n'
            '[policies.names]\npii_kinds = ["rrn", "frn", "passport", "driver", "card", "phone", "email", "secret", "brn", "crn", "account", "ipv4", "person", "address"]\n')
    path = tmp_path_factory.mktemp("cfg") / "gateway.toml"
    path.write_text(toml, encoding="utf-8")
    return make_stack(GATEWAY_CONFIG=str(path), GATEWAY_DETECT_URL=sidecar, GATEWAY_AUTH=None, GATEWAY_DETECTORS=None)


def test_h1_config_file_policy_masks_names_and_the_default_policy_never_calls_the_sidecar(cfg, sidecar):
    before = calls(sidecar)
    r = httpx.post(cfg.gateway + CHAT, json=chat(TEXT), headers={"Authorization": f"Bearer {NAMES_KEY}"})
    sent = json.loads(received(cfg)[-1])["messages"][0]["content"]
    assert r.status_code == 200 and NAME not in sent and ADDRESS not in sent and PHONE not in sent
    assert r.json()["choices"][0]["message"]["content"] == "[stub] " + TEXT and len(calls(sidecar)) == len(before) + 1
    before = calls(sidecar)
    r = httpx.post(cfg.gateway + CHAT, json=chat(TEXT), headers={"Authorization": f"Bearer {PLAIN_KEY}"})
    sent = json.loads(received(cfg)[-1])["messages"][0]["content"]
    assert r.status_code == 200 and NAME in sent and PHONE not in sent and calls(sidecar) == before


def test_h3_responses_stream_and_tool_arguments_restore_names(ner):
    with httpx.stream("POST", ner.gateway + RESPONSES, json={"model": "stub-stream", "input": TEXT, "stream": True}, timeout=30) as r:
        events = [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ")]
    assert "".join(e["delta"] for e in events if e.get("type") == "response.output_text.delta") == "[stub] " + TEXT
    assert next(e["text"] for e in events if e.get("type") == "response.output_text.done") == "[stub] " + TEXT
    r = httpx.post(ner.gateway + CHAT, json=chat(TEXT, "stub-toolcall"))
    args = r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args) == {"to": TEXT}
    history = [{"role": "user", "content": TEXT},
               {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "send_sms", "arguments": args}}]},
               {"role": "tool", "tool_call_id": "call_1", "content": f"{NAME} 님께 보냈습니다"}, {"role": "user", "content": "고마워"}]
    assert httpx.post(ner.gateway + CHAT, json={"model": "stub-model", "messages": history}).status_code == 200
    raw = received(ner)[-1]
    assert NAME not in raw and ADDRESS not in raw and PHONE not in raw
    with httpx.stream("POST", ner.gateway + MESSAGES, json={"model": "stub-stream-tool", "max_tokens": 50, "stream": True,
                                                            "messages": [{"role": "user", "content": TEXT}]}, timeout=30) as r:
        events = [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ")]
    partial = "".join(e["delta"]["partial_json"] for e in events if e.get("type") == "content_block_delta" and e["delta"].get("type") == "input_json_delta")
    assert json.loads(partial) == {"to": TEXT, "note": f"메모 {TEXT}"}


def test_h7_open_mode_stream_passes_after_a_sidecar_failure(ner_open):
    with httpx.stream("POST", ner_open.gateway + CHAT, json=chat(f"@@500@@ {NAME} {PHONE}", "stub-stream", stream=True), timeout=30) as r:
        body = r.read()
    assert content_of(body) == f"[stub] @@500@@ {NAME} {PHONE}"
    sent = json.loads(received(ner_open)[-1])["messages"][0]["content"]
    assert NAME in sent and PHONE not in sent


def test_h2_the_same_name_twice_gets_one_surrogate(ner):
    text = f"{NAME} 님과 {NAME} 님, 그리고 {ADDRESS}와 {ADDRESS}"
    r = httpx.post(ner.gateway + CHAT, json=chat(text))
    sent = json.loads(received(ner)[-1])["messages"][0]["content"]
    fake = sent.split(" 님")[0]
    assert NAME not in sent and ADDRESS not in sent and sent.count(fake) == 2
    assert r.json()["choices"][0]["message"]["content"] == "[stub] " + text and r.headers["x-gateway-pii"] == "issued=2 restored=4"


@pytest.mark.anyio
async def test_h4_client_batches_by_count_and_evicts_the_oldest_cache_entries(monkeypatch):
    from gateway import detect_client
    from gateway.detect_client import DetectClient
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert len(body["texts"]) <= 1024 and sum(len(x["text"]) for x in body["texts"]) <= 12_000
        posts.append(len(body["texts"]))
        return httpx.Response(200, json={"results": [{"id": x["id"], "pii_ner": []} for x in body["texts"]], "ms": 1})

    c = DetectClient("http://detect.test")
    c._client = httpx.AsyncClient(base_url="http://detect.test", transport=httpx.MockTransport(handler))
    texts = [f"t{i}" for i in range(1500)]
    await c.spans(texts)
    assert posts == [1024, 476]
    posts.clear()
    await c.spans(texts)
    assert posts == []                                                   # 모두 캐시
    monkeypatch.setattr(detect_client, "CACHE_SIZE", 10)
    await c.spans(["new-a"])                                             # 가장 오래된 t0가 밀려난다
    posts.clear()
    await c.spans(["t0"])
    assert posts == [1]
    posts.clear()
    await c.spans(["t5"])
    assert posts == []
