"""D-125: 탐지 사이드카 — 디코더(가짜 로짓, numpy만)와 실제 모델의 HTTP 계약.

  DETECT_MODEL_DIR=models python -m pytest -q detect/tests      # CI detect 작업(저장소 뿌리에서 — python -m이어야 detect를 import한다). 모델 폴더가 없으면 모델 테스트는 건너뛴다

게이트웨이 가상환경에는 numpy·onnxruntime이 없다 — 이 파일은 tests/가 아니라 여기 있고, CI의 detect 작업이 따로 돌린다.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from detect.decode import scheme, tag_spans, tidy, viterbi, windows

BIOES = {0: "O", 1: "B-PERSON", 2: "I-PERSON", 3: "E-PERSON", 4: "S-PERSON", 5: "B-ADDRESS", 6: "I-ADDRESS", 7: "E-ADDRESS", 8: "S-ADDRESS"}
BIO = {0: "O", 1: "B-PERSON", 2: "I-PERSON", 3: "B-ADDRESS", 4: "I-ADDRESS"}


def valid(path: list[str], bioes: bool) -> bool:
    prev = "O"
    for tag in path + (["O"] if bioes else []):
        p, t = ("O", "") if tag == "O" else tag.split("-", 1)
        q, u = ("O", "") if prev == "O" else prev.split("-", 1)
        if p in ("I", "E") and not (q in ("B", "I") and u == t):
            return False
        if bioes and p in ("O", "B", "S") and q in ("B", "I"):
            return False
        prev = tag
    return True


@pytest.mark.parametrize("labels", [BIOES, BIO], ids=["bioes", "bio"])
def test_d1_viterbi_is_the_best_valid_path(labels):
    """D1: 비터비는 규칙을 지키는 열 가운데 점수가 가장 높은 것이다 — 작은 문제에서 모든 열을 세어 대조한다. 규칙을 어기는 열은 고르지 않는다."""
    sc = scheme(labels)
    bioes = labels is BIOES
    rng = np.random.default_rng(7)
    names = [labels[i] for i in range(len(labels))]
    for _ in range(60):
        n = int(rng.integers(1, 5))
        lp = rng.normal(size=(n, len(labels))).astype(np.float32)
        path = viterbi(lp, sc)
        assert valid([names[i] for i in path], bioes)
        best = max(sum(lp[t, c[t]] for t in range(n)) for c in itertools.product(range(len(labels)), repeat=n)
                   if valid([names[i] for i in c], bioes))
        assert abs(sum(lp[t, path[t]] for t in range(n)) - best) < 1e-4


def test_d2_windows_cover_every_token_once_with_context():
    """D2: 창이 가진 구간을 이어 붙이면 [0, n)을 한 번씩 덮고, 창 안쪽 경계 양옆에 겹친 문맥이 남는다(긴 입력의 구간이 창 경계에서 잘리지 않게)."""
    for n in [*range(1, 60, 7), *range(500, 3000, 113)]:
        ws = windows(n, 510, 128)
        assert ws[0][2] == 0 and ws[-1][3] == n
        for (a, b, oa, ob), nxt in zip(ws, ws[1:] + [None]):
            assert 0 <= a <= oa < ob <= b <= n and b - a <= 510
            if nxt is not None:
                assert ob == nxt[2] and b - ob >= 64 - 1 and nxt[2] - nxt[0] >= 64 - 1


def test_d2b_windows_reject_bad_stride_and_shared_offsets_make_one_span():
    """D2b: 겹침이 창 크기 이상이면 창을 만들지 않는다(가진 구간이 어긋난다). 같은 위치를 나눠 가진 조각(홀로 선 '▁'과 첫 글자)은 구간 하나로 잇는다."""
    for stride in (510, 600):
        with pytest.raises(ValueError):
            windows(2000, 510, stride)
    spans = tag_spans(["B-PERSON", "B-PERSON", "I-PERSON", "S-PERSON", "B-PERSON", "O"], [0.9] * 6,
                      [(4, 5), (4, 5), (5, 7), (9, 10), (9, 10), (11, 12)])
    assert [(s["start"], s["end"]) for s in spans] == [(4, 7), (9, 10)]
    text = "담당 김철수 님께"
    assert [(s["start"], s["end"]) for s in tidy([{"start": 3, "end": 8, "label": "PERSON", "score": 0.9}], text, {"PERSON": "person"})] == [(3, 6)]


def test_d3_tag_spans_lenient_and_tidy_strips_particles():
    """D3: 규칙 밖 태그(O 뒤 I-)도 구간을 잃지 않는다. 이름 끝의 조사·호칭은 떼고 이름 일부인 '아'는 남긴다. 공백 하나로 붙은 주소 조각은 잇는다."""
    text = "김철수에게 이수아 지훈아 서울 강남구 테헤란로 1"
    offs = [(0, 2), (2, 3), (3, 5), (6, 8), (8, 9), (10, 12), (12, 13), (14, 16), (17, 20), (21, 25), (26, 27)]
    tags = ["B-PERSON", "I-PERSON", "E-PERSON", "I-PERSON", "E-PERSON", "B-PERSON", "E-PERSON", "S-ADDRESS", "S-ADDRESS", "B-ADDRESS", "E-ADDRESS"]
    spans = tag_spans(tags, [0.9] * len(tags), offs)
    assert [(s["label"], text[s["start"]:s["end"]]) for s in spans][:3] == [("PERSON", "김철수에게"), ("PERSON", "이수아"), ("PERSON", "지훈아")]
    got = [(s["label"], text[s["start"]:s["end"]]) for s in tidy(spans, text, {"ADDRESS": "address", "PERSON": "person"})]
    assert got == [("PERSON", "김철수"), ("PERSON", "이수아"), ("PERSON", "지훈"), ("ADDRESS", "서울 강남구 테헤란로 1")]


# --- 실제 모델 -------------------------------------------------------------------------------
MODEL_DIR = Path(os.environ.get("DETECT_MODEL_DIR", "models"))
NAME = "veil-ko-lite-int8"
need_model = pytest.mark.skipif(not (MODEL_DIR / NAME).exists(), reason=f"모델 폴더 없음: {MODEL_DIR / NAME}(python -m detect.fetch)")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from detect.app import create_app
    from detect.ner import NER
    with TestClient(create_app(NER(NAME, MODEL_DIR, threads=2))) as c:
        yield c


@need_model
def test_m1_health_reports_pinned_hash(client):
    """M1: /health는 실제로 연 ONNX 파일의 해시(목록과 같아야 열린다)·리비전·라이선스를 알린다."""
    want = json.loads(Path(__file__).parents[1].joinpath("models.json").read_text(encoding="utf-8"))[NAME]
    info = client.get("/health").json()["tasks"]["pii_ner"]
    assert info == {"model": want["id"], "revision": want["revision"], "license": want["license"], "sha256": want["files"][want["onnx"]]}


@need_model
def test_m2_detect_contract(client):
    """M2: 결과는 보낸 순서·id 그대로, 구간은 원문 문자 위치이고 제품 종류(kind)가 붙는다. 빈 텍스트는 빈 목록."""
    texts = [{"id": "a", "role": "user", "text": "담당자 김철수(010-1234-5678)에게 문의해 주세요."},
             {"id": "b", "role": "tool", "text": "배송지: 경기도 성남시 분당구 판교역로 235, 7층"}, {"id": "c", "role": "user", "text": "   "}]
    r = client.post("/v1/detect", json={"texts": texts, "tasks": ["pii_ner"]})
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body["results"]] == ["a", "b", "c"] and body["results"][2]["pii_ner"] == []
    for t, res in zip(texts, body["results"]):
        for s in res["pii_ner"]:
            assert 0 <= s["start"] < s["end"] <= len(t["text"]) and s["kind"] in ("person", "address", "org", None)
    a = {(s["kind"], texts[0]["text"][s["start"]:s["end"]]) for s in body["results"][0]["pii_ner"]}
    b = {(s["kind"], texts[1]["text"][s["start"]:s["end"]]) for s in body["results"][1]["pii_ner"]}
    assert ("person", "김철수") in a and ("address", "경기도 성남시 분당구 판교역로 235, 7층") in b


@need_model
def test_m3_bad_requests_and_no_echo(client):
    """M3: 틀린 요청은 400·413이고 오류 본문에 요청 내용이 없다."""
    marker = "홍길동비밀표지"

    def raw(obj: object) -> bytes:
        return json.dumps(obj, ensure_ascii=False).encode()       # 원문 UTF-8로 — 이스케이프로 보내면 되돌려 실은 본문을 표지로 못 잡는다
    cases = [(b"{not json " + marker.encode(), 400, "invalid_json"),
             (b"[" * 100_000 + b"]" * 100_000, 400, "invalid_json"),                                 # 깊은 중첩(RecursionError)
             (raw({"texts": [{"id": 1, "text": marker}]}), 400, "invalid_texts"),
             (json.dumps({"texts": [{"id": "\ud800", "text": marker}]}).encode(), 400, "invalid_texts"),            # 짝 없는 서로게이트 id
             (raw({"texts": [{"id": "a", "text": marker}], "tasks": ["injection"]}), 400, "invalid_tasks"),
             (raw({"texts": []}), 400, "invalid_texts"),
             (raw({"texts": [{"id": "a", "text": marker * 200_000}]}), 413, "request_too_large"),
             (raw({"texts": [{"id": str(i), "text": marker * 400} for i in range(20)]}), 413, "too_many_tokens"),     # 토큰 합
             (raw({"texts": [{"id": "a", "text": "x " * 70_000}]}), 413, "too_many_tokens")]                         # 글자 합(세지 않고)
    for body, status, code in cases:
        r = client.post("/v1/detect", content=body, headers={"content-type": "application/json"})
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), (code, r.text[:200])
        assert marker not in r.text and json.dumps(marker)[1:-1] not in r.text


@need_model
def test_m4_long_text_keeps_names_across_windows(client):
    """M4: 512토큰을 넘는 입력도 끝까지 본다 — 창 경계 근처에 놓인 이름까지 모두 정확한 위치로 찾는다."""
    filler = "이번 분기 정산 자료는 공유 폴더에 올려 두었고 검토 의견은 다음 회의 전까지 정리해 주세요. "
    names = ["김민준", "이서연", "박지호", "최수아", "정우진", "강하은", "조현우", "윤지민"]
    text, spots = "", []
    for i in range(48):
        text += filler
        if i % 6 == 5:
            name = names[len(spots)]
            text += f"담당자 {name} 님께 확인 부탁드립니다. "
            spots.append((text.index(name, len(text) - 30), name))
    r = client.post("/v1/detect", json={"texts": [{"id": "long", "text": text}], "tasks": ["pii_ner"]})
    got = {(s["start"], text[s["start"]:s["end"]]) for s in r.json()["results"][0]["pii_ner"] if s["kind"] == "person"}
    assert set(spots) <= got, sorted(set(spots) - got)


@need_model
def test_m5_hash_mismatch_refuses_to_load(tmp_path):
    """M5: 파일 하나라도 목록의 SHA-256과 다르면 열지 않는다 — /health의 해시가 실제로 돈 파일의 해시라는 보장."""
    from detect.ner import NER
    (tmp_path / NAME).mkdir()
    for f in (MODEL_DIR / NAME).iterdir():
        (tmp_path / NAME / f.name).symlink_to(f.resolve())
    (tmp_path / NAME / "config.json").unlink()
    shutil.copy(MODEL_DIR / NAME / "config.json", tmp_path / NAME / "config.json")
    with (tmp_path / NAME / "config.json").open("a") as fh:
        fh.write("\n")
    with pytest.raises(RuntimeError, match="config.json"):
        NER(NAME, tmp_path)


@need_model
def test_m6_lone_surrogate_and_long_unspaced_runs(client):
    """M6: 짝 없는 서로게이트가 든 텍스트도 200이고 위치는 원문 그대로다(U+FFFD로 바꿔 본다). 띄어쓰기 없이 100자를 넘는 덩어리 속 이름도 찾는다(WordPiece [UNK] 방지)."""
    text = "담당자 김철수 님께 \ud800 문의해 주세요."
    r = client.post("/v1/detect", content=json.dumps({"texts": [{"id": "a", "text": text}], "tasks": ["pii_ner"]}),
                    headers={"content-type": "application/json"})
    assert r.status_code == 200
    got = {(s["kind"], s["start"], s["end"]) for s in r.json()["results"][0]["pii_ner"]}
    assert ("person", 4, 7) in got
    long = "가" * 70 + "담당자김철수님께" + "나" * 70
    spans = client.post("/v1/detect", json={"texts": [{"id": "b", "text": long}], "tasks": ["pii_ner"]}).json()["results"][0]["pii_ner"]
    assert any(s["kind"] == "person" and "김철수" in long[s["start"]:s["end"]] for s in spans), spans


@need_model
def test_m7_decomposed_hangul_and_combining_marks(client):
    """M7: 풀어 쓴 한글(NFD)과 결합 부호가 붙은 이름도 찾고, 구간은 원문의 자모·부호까지 덮는다(가리면 한 글자도 남지 않게)."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", "담당자 김철수 님께 서울특별시 강남구 테헤란로 152로 보내 주세요.")
    marked = "담당자 김철수\u0301 님께 문의해 주세요."
    out = client.post("/v1/detect", json={"texts": [{"id": "a", "text": nfd}, {"id": "b", "text": marked}], "tasks": ["pii_ner"]}).json()["results"]
    a = {(s["kind"], unicodedata.normalize("NFC", nfd[s["start"]:s["end"]])) for s in out[0]["pii_ner"]}
    assert ("person", "김철수") in a and ("address", "서울특별시 강남구 테헤란로 152") in a
    person = next(s for s in out[0]["pii_ner"] if s["kind"] == "person")
    assert nfd[person["start"]:person["end"]] == unicodedata.normalize("NFD", "김철수")
    assert any(s["kind"] == "person" and marked[s["start"]:s["end"]] == "김철수\u0301" for s in out[1]["pii_ner"])
