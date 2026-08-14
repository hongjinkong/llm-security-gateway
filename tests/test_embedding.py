"""임베더 테스트 — D-043의 "주입 가능한 인터페이스" 요건을 지키는 곳.

이 파일의 테스트는 **네트워크를 쓰지 않는다.** `httpx.MockTransport`로 Ollama를 흉내낸다.
실제 Ollama를 부르는 것은 `scripts/embed_latency.py`뿐이고, 그건 측정 도구지 테스트가 아니다.

*** 이 파일을 고칠 때 읽을 것 ***
`FakeEmbedder`가 있는 이유는 편해서가 아니라 **점수를 통제하기 위해서**다.
점수를 통제 못 하면 2차 탐지기 테스트의 단언문이 "나온 값이 나왔다"가 되고,
그런 테스트는 판정 로직이 망가져도 통과한다.
`test_fake_embedder_can_produce_both_verdicts_worth_of_scores`가 그 능력 자체를 못 박는다.
"""
from __future__ import annotations

import math

import httpx
import pytest

from gateway.embedding import (
    EmbeddingError,
    FakeEmbedder,
    OllamaEmbedder,
    check_norm_canary,
    l2_normalize,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def cos(a, b) -> float:
    """정규화된 벡터끼리는 코사인 유사도 = 내적."""
    return sum(x * y for x, y in zip(a, b))


def unit(*vals: float) -> list[float]:
    return l2_normalize(list(vals))


# --- 정규화와 카나리 -----------------------------------------------------------

def test_l2_normalize_makes_unit_length():
    v = l2_normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)
    assert math.isclose(v[0], 0.6) and math.isclose(v[1], 0.8)


def test_l2_normalize_rejects_zero_vector():
    """영벡터를 조용히 통과시키면 그 항목과의 유사도가 **항상 0**이 되어
    코퍼스에서 사라진 것과 같아진다. 조용한 소실이라 아무도 눈치채지 못한다."""
    with pytest.raises(EmbeddingError):
        l2_normalize([0.0, 0.0, 0.0])


def test_norm_canary_passes_on_unit_vectors():
    assert check_norm_canary([unit(1, 1), unit(0, 5)]) is None


def test_norm_canary_catches_unnormalized_vectors():
    """카나리는 정확성 장치가 아니라 **모델·엔드포인트 교체 감지기**다.
    우리가 어차피 정규화하므로 코사인 점수는 계속 그럴듯하게 나온다 — 다른 모델의
    그럴듯한 값이다. D-036의 '실행 중 코드 지문 보고'와 같은 동기."""
    bad = check_norm_canary([unit(1, 0), [3.0, 4.0]])
    assert bad is not None and math.isclose(bad, 5.0)


# --- OllamaEmbedder: 가짜 전송으로 계약 확인 ------------------------------------

def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ok_handler(vectors, *, capture: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            import json as _json
            capture.append({"url": str(request.url), "body": _json.loads(request.content)})
        return httpx.Response(200, json={"embeddings": vectors})
    return handler


@pytest.mark.anyio
async def test_ollama_embedder_hits_api_embed_with_batch_input():
    """`scripts/embed_latency.py`와 **같은 엔드포인트·같은 필드**를 써야 한다.
    두 곳이 갈라지면 D-043의 지연 사전 게이트가 실제 경로와 다른 것을 재게 된다.

    배치인 것도 계약이다 — 코퍼스 52항목을 52번 왕복하면 기동이 8초 늘어난다."""
    seen: list = []
    async with make_client(ok_handler([unit(1, 0), unit(0, 1)], capture=seen)) as c:
        emb = OllamaEmbedder(c, model="bge-m3", endpoint="http://localhost:11434")
        out = await emb.embed(["가", "나"])

    assert len(out) == 2
    assert seen[0]["url"].endswith("/api/embed")
    assert seen[0]["body"]["model"] == "bge-m3"
    assert seen[0]["body"]["input"] == ["가", "나"], "배치를 한 번에 보낸다"
    assert len(seen) == 1, "2건을 2번 왕복하지 않는다"


@pytest.mark.anyio
async def test_ollama_embedder_preserves_order_and_count():
    """순서가 밀리면 최근접 항목 ID가 통째로 거짓말이 된다 — 감사 로그가 조용히 오염된다."""
    async with make_client(ok_handler([unit(1, 0), unit(0, 1), unit(1, 1)])) as c:
        out = await OllamaEmbedder(c).embed(["a", "b", "c"])
    assert len(out) == 3
    assert math.isclose(cos(out[0], out[1]), 0.0, abs_tol=1e-9)
    assert cos(out[0], out[2]) > 0.7


@pytest.mark.anyio
async def test_ollama_embedder_rejects_count_mismatch():
    async with make_client(ok_handler([unit(1, 0)])) as c:
        with pytest.raises(EmbeddingError, match="개수 불일치"):
            await OllamaEmbedder(c).embed(["a", "b"])


@pytest.mark.anyio
async def test_ollama_embedder_rejects_dimension_change_between_calls():
    """1024 → 384는 bge-m3 → all-minilm이다. D-043의 폴백 모델로 **조용히** 갈아타면
    코사인 점수는 계속 나오지만 다른 좌표계의 값이다."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        vec = unit(1, 0) if calls["n"] == 1 else unit(1, 0, 0)
        return httpx.Response(200, json={"embeddings": [vec]})

    async with make_client(handler) as c:
        emb = OllamaEmbedder(c)
        await emb.embed(["a"])
        assert emb.dim == 2
        with pytest.raises(EmbeddingError, match="차원이 바뀌었다"):
            await emb.embed(["b"])


@pytest.mark.anyio
async def test_ollama_embedder_rejects_mixed_dimensions_in_one_response():
    async with make_client(ok_handler([unit(1, 0), unit(1, 0, 0)])) as c:
        with pytest.raises(EmbeddingError, match="차원이 섞여"):
            await OllamaEmbedder(c).embed(["a", "b"])


@pytest.mark.anyio
async def test_ollama_embedder_norm_canary_fires_by_default():
    async with make_client(ok_handler([[3.0, 4.0]])) as c:
        with pytest.raises(EmbeddingError, match="단위 길이가 아니다"):
            await OllamaEmbedder(c).embed(["a"])


@pytest.mark.anyio
async def test_ollama_embedder_norm_canary_can_be_relaxed_but_records():
    """폴백 모델을 실제로 검토할 때 카나리를 끄고 돌려볼 수 있어야 한다.
    끄더라도 **관측값은 남긴다** — 껐다는 사실이 조용해지면 안 된다."""
    async with make_client(ok_handler([[3.0, 4.0]])) as c:
        emb = OllamaEmbedder(c, strict_norm=False)
        out = await emb.embed(["a"])
    assert math.isclose(emb.observed_norm, 5.0)
    assert math.isclose(math.sqrt(sum(x * x for x in out[0])), 1.0), "그래도 정규화는 한다"


@pytest.mark.anyio
async def test_ollama_embedder_does_not_swallow_transport_errors():
    """D-030 fail-open 금지. 0벡터를 돌려주면 모든 유사도가 0이 되어 **방어가 꺼진 채로
    '방어 ON' 측정**이 된다. chain.py가 '가장 나쁜 실패'라고 부른 것."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with make_client(handler) as c:
        with pytest.raises(EmbeddingError, match="Ollama 임베딩 실패"):
            await OllamaEmbedder(c).embed(["a"])


@pytest.mark.anyio
async def test_ollama_embedder_raises_on_http_error_status():
    async with make_client(lambda r: httpx.Response(500, text="boom")) as c:
        with pytest.raises(EmbeddingError):
            await OllamaEmbedder(c).embed(["a"])


@pytest.mark.anyio
async def test_ollama_embedder_error_message_does_not_leak_input_text():
    """D-029 — 본문 원문은 어디에도 기록하지 않는다. 예외 메시지도 로그로 간다."""
    secret = "주민번호 950720-1456782 관련 문의입니다"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with make_client(handler) as c:
        with pytest.raises(EmbeddingError) as ei:
            await OllamaEmbedder(c).embed([secret])
    assert secret not in str(ei.value)
    assert "950720" not in str(ei.value)


@pytest.mark.anyio
async def test_ollama_embedder_short_circuits_empty_input():
    """빈 목록에 왕복을 쓰지 않는다."""
    seen: list = []
    async with make_client(ok_handler([], capture=seen)) as c:
        assert await OllamaEmbedder(c).embed([]) == []
    assert seen == []


# --- FakeEmbedder --------------------------------------------------------------

@pytest.mark.anyio
async def test_fake_embedder_is_deterministic_and_ordered():
    emb = FakeEmbedder({"가": [1.0, 0.0], "나": [0.0, 1.0]})
    a = await emb.embed(["가", "나", "가"])
    b = await emb.embed(["가", "나", "가"])
    assert a == b
    assert a[0] == a[2] and a[0] != a[1]


@pytest.mark.anyio
async def test_fake_embedder_normalizes_like_production():
    """fake가 프로덕션과 다른 경로를 타면, 테스트가 통과하는 코드가 프로덕션에서 깨진다."""
    out = await FakeEmbedder({"x": [3.0, 4.0]}).embed(["x"])
    assert math.isclose(math.sqrt(sum(v * v for v in out[0])), 1.0)


@pytest.mark.anyio
async def test_fake_embedder_refuses_unregistered_text_by_default():
    """조용한 기본값은 '무엇을 재고 있는지 모르는 테스트'를 만든다."""
    with pytest.raises(EmbeddingError, match="등록되지 않은"):
        await FakeEmbedder({"가": [1.0, 0.0]}).embed(["나"])


@pytest.mark.anyio
async def test_fake_embedder_default_is_opt_in():
    emb = FakeEmbedder({"가": [1.0, 0.0]}, default=[0.0, 1.0])
    out = await emb.embed(["나"])
    assert math.isclose(out[0][1], 1.0)


@pytest.mark.anyio
async def test_fake_embedder_rejects_mixed_dimensions():
    """fake가 프로덕션보다 관대하면 못 잡는 버그가 생긴다."""
    with pytest.raises(EmbeddingError, match="차원이 섞여"):
        await FakeEmbedder({"가": [1.0, 0.0], "나": [1.0, 0.0, 0.0]}).embed(["가", "나"])


@pytest.mark.anyio
async def test_fake_embedder_records_what_was_embedded():
    """2차 탐지기가 **요청당 1문장만** 임베딩하는지 확인할 때 쓴다(D-043 비용 구조).
    코퍼스는 기동 시 1회, 요청 처리에는 1건이어야 한다."""
    emb = FakeEmbedder({"가": [1.0, 0.0], "나": [0.0, 1.0]})
    await emb.embed(["가", "나"])
    await emb.embed(["가"])
    assert emb.calls == [["가", "나"], ["가"]]


@pytest.mark.anyio
async def test_fake_embedder_can_produce_both_verdicts_worth_of_scores():
    """**이 파일에서 가장 중요한 테스트.**

    fake의 존재 이유는 편의가 아니라 '점수를 원해서 만들 수 있다'는 것이다.
    그 능력이 없으면 2차 탐지기 테스트가 전부 '나온 값이 나왔다'가 된다.
    여기서 T 위·아래·동점을 실제로 만들 수 있음을 못 박는다.
    """
    emb = FakeEmbedder({
        "코퍼스항목": [1.0, 0.0],
        "거의같은요청": [0.99, 0.141],   # 코사인 ≈ 0.990
        "애매한요청": [0.7, 0.714],      # 코사인 ≈ 0.700
        "무관한요청": [0.0, 1.0],        # 코사인 = 0.000
    })
    c, hi, mid, lo = await emb.embed(["코퍼스항목", "거의같은요청", "애매한요청", "무관한요청"])

    assert cos(c, hi) > 0.95, "T 위를 만들 수 있다"
    assert 0.6 < cos(c, mid) < 0.8, "T 부근을 만들 수 있다"
    assert cos(c, lo) < 0.05, "T 아래를 만들 수 있다"
    assert cos(c, hi) > cos(c, mid) > cos(c, lo), "순서를 지정할 수 있다 = 최근접 선택을 시험할 수 있다"
