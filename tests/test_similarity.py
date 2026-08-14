"""유사도 검사기 테스트 — 5단계 2차. 근거 D-043·D-044·D-048.

`FakeEmbedder`로 **점수를 지정해서** 돌린다(D-047). 그래야 "T 바로 위", "T 바로 아래",
"최근접이 둘 중 어느 쪽" 같은 상황을 원해서 만들 수 있다. 실제 임베딩으로는
나온 값을 읽을 수만 있어서 단언문이 "나온 값이 나왔다"가 된다.

*** 이 파일에서 제일 중요한 두 가지 ***
1. `test_allow_still_records_the_score` — D-044는 **판정과 무관하게 전량 로깅**을
   요구한다. 통과한 요청의 점수가 안 남으면 "T가 달랐다면"을 재측정 없이 계산할 수 없다.
2. `test_inspect_without_prepare_raises` — 준비 안 된 검사기가 조용히 통과시키면
   **방어가 꺼진 채로 "방어 ON" 측정**이 된다. chain.py가 "가장 나쁜 실패"라 부른 것.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from gateway.chain import DetectorChain
from gateway.detectors.base import Action, Inspection
from gateway.detectors.similarity import (
    CorpusError,
    InjectionSimilarityDetector,
    load_corpus,
    threshold_from_env,
)
from gateway.embedding import EmbeddingError, FakeEmbedder


@pytest.fixture
def anyio_backend():
    return "asyncio"


# 2차원 벡터로 시험한다. 각도만 지정하면 코사인 유사도가 곧바로 나온다.
def ray(deg: float) -> list[float]:
    r = np.deg2rad(deg)
    return [float(np.cos(r)), float(np.sin(r))]


CORPUS = [
    {"id": "K-T-01", "text": "공격문장하나", "source": "category_ko", "category": "R1"},
    {"id": "K-T-02", "text": "공격문장둘", "source": "category_ko", "category": "R3"},
]


@pytest.fixture
def corpus_file(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in CORPUS) + "\n",
                 encoding="utf-8")
    return p


def emb_with(extra: dict[str, list[float]]) -> FakeEmbedder:
    """코퍼스 2항목은 0도·90도에 고정하고, 질의만 각도를 바꿔가며 지정한다."""
    return FakeEmbedder({"공격문장하나": ray(0), "공격문장둘": ray(90), **extra})


def body(text: str, *, ensure_ascii: bool = False) -> bytes:
    return json.dumps({"message": text}, ensure_ascii=ensure_ascii).encode("utf-8")


def insp(text: str, **kw) -> Inspection:
    return Inspection(request_id="rid", method="POST", path="/chat", headers={},
                      body=body(text, **kw))


async def ready(embedder, corpus_file, **kw) -> InjectionSimilarityDetector:
    det = InjectionSimilarityDetector(embedder, corpus_path=corpus_file, **kw)
    await det.prepare()
    return det


# --- 구성: T가 없으면 기동하지 못한다 (D-048) ----------------------------------

def test_enforce_mode_requires_a_threshold(corpus_file):
    """T는 D-044가 '측정 전 동결'로 못 박은 값이다. 기본값을 두면 동결 안 된 T로
    EVAL 5.2 행을 채울 수 있다."""
    with pytest.raises(ValueError, match="임계값 T가 필요하다"):
        InjectionSimilarityDetector(FakeEmbedder(), corpus_path=corpus_file)


def test_observe_mode_does_not_require_a_threshold(corpus_file):
    det = InjectionSimilarityDetector(FakeEmbedder(), corpus_path=corpus_file, observe=True)
    assert det.name == "injection_similarity_observe"


def test_detector_names_differ_so_the_env_string_records_the_mode(corpus_file):
    """`GATEWAY_DETECTORS` 문자열 자체가 어느 쪽이 돌았는지를 기록해야 한다 —
    D-036의 코드 지문 보고와 verify_gateway.sh가 그대로 잡는다."""
    a = InjectionSimilarityDetector(FakeEmbedder(), corpus_path=corpus_file, threshold=0.5)
    b = InjectionSimilarityDetector(FakeEmbedder(), corpus_path=corpus_file, observe=True)
    assert a.name == "injection_similarity"
    assert b.name != a.name


@pytest.mark.parametrize("bad", [1.5, -2.0])
def test_threshold_out_of_cosine_range_is_rejected(corpus_file, bad):
    with pytest.raises(ValueError, match="-1~1"):
        InjectionSimilarityDetector(FakeEmbedder(), corpus_path=corpus_file, threshold=bad)


def test_empty_env_threshold_is_none_not_zero():
    """`GATEWAY_SIMILARITY_T=` 를 '껐다'고 생각하는 실수가 '0.0으로 설정'으로 읽히면
    **모든 요청이 차단된다.**"""
    assert threshold_from_env({"GATEWAY_SIMILARITY_T": ""}) is None
    assert threshold_from_env({}) is None
    assert threshold_from_env({"GATEWAY_SIMILARITY_T": "0.72"}) == 0.72


def test_non_numeric_env_threshold_raises():
    with pytest.raises(ValueError, match="숫자가 아니다"):
        threshold_from_env({"GATEWAY_SIMILARITY_T": "높게"})


# --- 코퍼스 적재 ---------------------------------------------------------------

def test_missing_corpus_file_raises(tmp_path):
    with pytest.raises(CorpusError, match="없다"):
        load_corpus(tmp_path / "없는파일.jsonl")


def test_empty_corpus_raises(tmp_path):
    """코퍼스가 비면 최근접이 없어 **모든 요청이 통과**한다. 검사기가 있는데
    아무것도 안 하는 상태이고, 로그에는 'allow'만 남아 정상처럼 보인다."""
    p = tmp_path / "empty.jsonl"
    p.write_text("\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="비어 있다"):
        load_corpus(p)


def test_corpus_row_without_text_raises(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"id": "K-X", "text": ""}) + "\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="빈 행"):
        load_corpus(p)


@pytest.mark.anyio
async def test_prepare_embeds_the_whole_corpus_in_one_batch(corpus_file):
    """52항목을 낱개로 왕복하면 기동이 8초 늘어난다(D-043 실측 148ms/건)."""
    e = emb_with({})
    det = await ready(e, corpus_file, threshold=0.9)
    assert e.calls == [["공격문장하나", "공격문장둘"]], "한 번에 보낸다"
    assert det.matrix is not None and det.matrix.shape == (2, 2)


@pytest.mark.anyio
async def test_prepare_rejects_unnormalized_corpus_vectors(corpus_file, monkeypatch):
    """임베더가 정규화했어야 한다(D-047). 어긋나면 코사인이 아니라 그냥 내적이 되고,
    점수가 그럴듯한데 틀린 값이 된다."""
    e = emb_with({})

    async def fake_embed(texts):
        return [[3.0, 4.0] for _ in texts]      # 노름 5

    monkeypatch.setattr(e, "embed", fake_embed)
    det = InjectionSimilarityDetector(e, corpus_path=corpus_file, threshold=0.9)
    with pytest.raises(CorpusError, match="단위 길이가 아니다"):
        await det.prepare()


@pytest.mark.anyio
async def test_prepare_wraps_embedding_failure_as_corpus_error(corpus_file):
    det = InjectionSimilarityDetector(FakeEmbedder(), corpus_path=corpus_file, threshold=0.9)
    with pytest.raises(CorpusError, match="코퍼스 임베딩 실패"):
        await det.prepare()


# --- 판정 ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_inspect_without_prepare_raises(corpus_file):
    """**조용히 통과시키면 안 된다.** 준비 안 된 검사기를 달고 측정하면
    방어가 꺼진 채로 '방어 ON' 리포트가 나온다."""
    det = InjectionSimilarityDetector(emb_with({"질의": ray(0)}),
                                      corpus_path=corpus_file, threshold=0.9)
    with pytest.raises(CorpusError, match="prepare"):
        await det.inspect(insp("질의"))


@pytest.mark.anyio
async def test_score_above_threshold_blocks(corpus_file):
    det = await ready(emb_with({"질의": ray(10)}), corpus_file, threshold=0.90)
    v = await det.inspect(insp("질의"))
    assert v.action is Action.BLOCK          # cos(10°) ≈ 0.985
    assert v.meta["nearest_id"] == "K-T-01"
    assert v.meta["similarity"] > 0.98
    assert v.body is None, "BLOCK은 body를 돌려주지 않는다"


@pytest.mark.anyio
async def test_score_below_threshold_allows(corpus_file):
    det = await ready(emb_with({"질의": ray(45)}), corpus_file, threshold=0.90)
    v = await det.inspect(insp("질의"))
    assert v.action is Action.ALLOW          # cos(45°) ≈ 0.707


@pytest.mark.anyio
async def test_allow_still_records_the_score(corpus_file):
    """**D-044의 핵심.** 통과한 요청의 점수가 안 남으면 측정 후 'T가 달랐다면'을
    재측정 없이 계산할 수 없다. 남길 것: 점수 / 최근접 ID·source·category / 적용 T."""
    det = await ready(emb_with({"질의": ray(45)}), corpus_file, threshold=0.90)
    v = await det.inspect(insp("질의"))
    assert v.action is Action.ALLOW
    assert v.meta["similarity"] == pytest.approx(0.7071, abs=1e-3)
    assert v.meta["nearest_id"] == "K-T-01"
    assert v.meta["nearest_source"] == "category_ko"
    assert v.meta["nearest_category"] == "R1"
    assert v.meta["threshold"] == 0.90
    assert v.meta["mode"] == "enforce"


@pytest.mark.anyio
async def test_nearest_item_is_the_closest_one_not_the_first(corpus_file):
    """최근접 선택이 틀리면 감사 로그의 category별 기여도 분리(D-044)가 통째로 거짓말이 된다."""
    det = await ready(emb_with({"질의": ray(80)}), corpus_file, threshold=0.99)
    v = await det.inspect(insp("질의"))
    assert v.meta["nearest_id"] == "K-T-02", "90도 쪽이 더 가깝다"
    assert v.meta["nearest_category"] == "R3"


@pytest.mark.anyio
async def test_observe_mode_never_blocks_but_records(corpus_file):
    """캘리브레이션용. 점수가 아무리 높아도 차단하지 않는다 — 대신 이름이 달라서
    로그와 verify_gateway.sh가 관찰 모드였음을 증언한다."""
    det = await ready(emb_with({"질의": ray(0)}), corpus_file, observe=True)
    v = await det.inspect(insp("질의"))
    assert v.action is Action.ALLOW
    assert v.meta["similarity"] == pytest.approx(1.0, abs=1e-5)
    assert v.meta["mode"] == "observe"
    assert v.meta["threshold"] is None
    assert v.detector == "injection_similarity_observe"


@pytest.mark.anyio
async def test_observe_mode_never_blocks_even_when_a_threshold_is_set(corpus_file):
    """**변이 검사가 찾아낸 구멍**(2026-08-14, N3).

    main.py의 팩토리는 `observe=True`에도 `threshold_from_env()`를 그대로 넘긴다.
    `.env`에 `GATEWAY_SIMILARITY_T`가 남아 있으면 관찰 모드 검사기가 T를 들고 있게 되고,
    그때도 **절대 차단하면 안 된다.** 이 조합을 시험하지 않으면 나중에 `self.observe`
    조건이 빠져도 테스트가 통과한다 — 캘리브레이션 런이 조용히 차단을 시작한다.

    T를 들고 있는 것 자체는 허용한다. meta에 남겨두면 감사 로그를 읽을 때
    "그때 T가 얼마였나"를 알 수 있다(D-044).
    """
    det = await ready(emb_with({"질의": ray(0)}), corpus_file, observe=True, threshold=0.5)
    v = await det.inspect(insp("질의"))
    assert v.action is Action.ALLOW, "관찰 모드는 T가 있어도 차단하지 않는다"
    assert v.meta["similarity"] == pytest.approx(1.0, abs=1e-5)
    assert v.meta["threshold"] == 0.5, "적용됐을 T는 기록한다"
    assert v.meta["mode"] == "observe"


@pytest.mark.anyio
async def test_threshold_is_inclusive_at_the_boundary(corpus_file):
    """경계 규칙을 못 박는다 — `score >= T`면 차단. T를 정할 때 이 방향을 알아야 한다."""
    det = await ready(emb_with({"질의": ray(0)}), corpus_file, threshold=1.0)
    assert (await det.inspect(insp("질의"))).action is Action.BLOCK


@pytest.mark.anyio
async def test_block_reason_does_not_leak_corpus_text(corpus_file):
    """차단 사유로 룰을 역산당하면 안 된다(D-040). 코퍼스 원문은 어디에도 안 남는다(D-029)."""
    det = await ready(emb_with({"질의": ray(0)}), corpus_file, threshold=0.5)
    v = await det.inspect(insp("질의"))
    assert v.action is Action.BLOCK
    blob = v.reason + json.dumps(v.meta, ensure_ascii=False)
    for row in CORPUS:
        assert row["text"] not in blob
    assert "질의" not in blob, "요청 원문도 남기지 않는다"


# --- 입력 처리 -----------------------------------------------------------------

@pytest.mark.anyio
async def test_request_embeds_exactly_one_text(corpus_file):
    """D-043의 비용 구조 — 요청당 비용은 입력 1문장 임베딩이 전부."""
    e = emb_with({"질의": ray(45)})
    det = await ready(e, corpus_file, threshold=0.9)
    e.calls.clear()
    await det.inspect(insp("질의"))
    assert e.calls == [["질의"]]


@pytest.mark.anyio
async def test_verdict_is_independent_of_json_escaping(corpus_file):
    """`ensure_ascii=True`면 한글이 `\\uXXXX`가 된다. injection.py의 `user_text`를
    재사용하는 이유가 이것이다 — 새로 만들면 한쪽만 고치는 사고가 난다."""
    det = await ready(emb_with({"질의": ray(0)}), corpus_file, threshold=0.9)
    a = await det.inspect(insp("질의", ensure_ascii=False))
    b = await det.inspect(insp("질의", ensure_ascii=True))
    assert a.action is b.action is Action.BLOCK
    assert a.meta["similarity"] == b.meta["similarity"]


@pytest.mark.anyio
async def test_empty_input_is_not_embedded(corpus_file):
    e = emb_with({})
    det = await ready(e, corpus_file, threshold=0.9)
    e.calls.clear()
    v = await det.inspect(insp("   "))
    assert v.action is Action.ALLOW
    assert v.meta["similarity_skipped"] == "empty_input"
    assert e.calls == [], "빈 입력에 왕복을 쓰지 않는다"


@pytest.mark.anyio
async def test_embedding_failure_is_not_swallowed(corpus_file):
    """D-030 fail-open 금지. 여기서 ALLOW를 돌려주면 Ollama가 죽은 동안
    방어가 통째로 꺼진 채 측정이 계속된다."""
    e = emb_with({})                      # 질의는 등록하지 않았다
    det = await ready(e, corpus_file, threshold=0.9)
    with pytest.raises(EmbeddingError):
        await det.inspect(insp("등록되지않은질의"))


@pytest.mark.anyio
async def test_query_dimension_mismatch_raises(corpus_file):
    """1024 → 384는 bge-m3 → all-minilm이다. 조용히 갈아타면 점수는 계속 나오지만
    다른 좌표계의 값이다."""
    e = emb_with({"질의": [1.0, 0.0, 0.0]})
    det = await ready(e, corpus_file, threshold=0.9)
    with pytest.raises(CorpusError, match="차원"):
        await det.inspect(insp("질의"))


# --- 수명주기 훅 ---------------------------------------------------------------

@pytest.mark.anyio
async def test_chain_forwards_prepare_and_aclose(corpus_file):
    det = InjectionSimilarityDetector(emb_with({}), corpus_path=corpus_file, threshold=0.9)
    chain = DetectorChain([det])
    assert det.matrix is None
    await chain.prepare()
    assert det.matrix is not None
    await chain.aclose()
    assert det.matrix is None


@pytest.mark.anyio
async def test_existing_detectors_are_unaffected_by_the_new_hooks():
    """기본 구현이 no-op이므로 기존 검사기는 영향받지 않는다(D-030 계약 확장)."""
    from gateway.detectors.injection import InjectionRuleDetector
    chain = DetectorChain([InjectionRuleDetector()])
    await chain.prepare()
    await chain.aclose()
