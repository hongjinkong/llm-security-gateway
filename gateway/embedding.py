"""임베더 — 문장을 좌표로 바꾸는 자. 5단계 2차 유사도 탐지기의 부품. 근거는 D-043.

도서관 사서 비유: 책을 주제별 좌표에 꽂는다. "연차 신청 절차"와 "휴가는 며칠 전에
내나요"는 가까운 선반에, "급여계좌 변경"은 먼 선반에 간다. 2차 탐지기는 들어온 요청을
같은 좌표계에 꽂아보고 **코퍼스 항목 중 가장 가까운 것과의 거리**를 잰다.

이 파일이 만드는 것은 사서가 아니라 **사서를 갈아끼울 수 있는 자리**다.

왜 인터페이스로 분리하나 (D-043이 "선택이 아니라 설계 요건"이라고 못 박은 이유):
  1. 테스트가 실제 Ollama를 부르면 느려지고(요청당 150ms) 외부 서비스에 의존한다.
  2. **판정 로직을 시험하려면 점수를 내가 정할 수 있어야 한다.** 2차 탐지기에서
     시험할 것은 임베딩 품질이 아니라 "점수가 T를 넘으면 BLOCK 하는가 / 최근접 항목을
     제대로 고르는가 / 로그에 ID·source·category를 남기는가"다. 진짜 임베더로는
     "0.63이 나왔다"까지만 알 뿐 0.63을 **원해서** 만들 수가 없다.
     점수를 통제 못 하면 단언문이 "나온 값이 나왔다"가 되고, 그런 테스트는 로직이
     망가져도 통과한다 — 룰 사전을 비웠는데 코퍼스 테스트가 조용히 통과한 것과 같다.

검사기가 아니므로 `detectors/` 밖에 둔다. `Detector`를 상속하지 않는다.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence

import httpx

# D-043: 벡터 차원 1024 (bge-m3). 폴백 후보 all-minilm은 384라 값이 다르다.
# 차원을 상수로 박지 않고 **첫 호출에서 관측한 값에 고정**한다 — 모델을 바꿀 때
# 상수를 같이 고쳐야 하는 구조는 잊어버리기 쉽고, 잊으면 조용히 틀린다.

# 노름 카나리 허용 오차. /api/embed는 L2 정규화된 벡터를 준다고 문서화돼 있다.
# 부동소수 오차만 허용하고 그 밖은 "모델이나 엔드포인트가 바뀌었다"로 읽는다.
NORM_TOLERANCE = 1e-3


class EmbeddingError(RuntimeError):
    """임베딩 실패. **삼키지 않고 위로 올린다.**

    D-030이 fail-open을 금지한다. 여기서 0벡터를 돌려주면 모든 요청의 유사도가 0이 되어
    **방어가 꺼진 채로 "방어 ON" 측정**이 된다. chain.py가 "이 프로젝트에서 가장 나쁜
    실패"라고 부른 것이 정확히 이것이다. 시끄럽게 실패하는 쪽이 안전하다.
    """


class Embedder(ABC):
    """문장 목록 → 벡터 목록. 순서와 개수를 보존한다.

    async인 이유는 `Detector.inspect`와 같다 — 외부 HTTP를 부르는 구현이 있기 때문이다.

    배치로 받는 이유: 기동 시 코퍼스 52항목을 **한 번에** 임베딩한다. 52번 왕복하면
    기동이 8초 늘어난다(맥북 실측 148ms/건, D-043). 요청 처리 때는 길이 1로 부른다.
    """

    name: str = "unnamed"

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """벡터를 돌려준다. 실패하면 EmbeddingError를 던진다(빈 값·0벡터 금지)."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """소유한 자원을 닫는다. 주입받은 클라이언트는 닫지 않는다(소유자가 닫는다)."""
        return None


def l2_normalize(vec: Sequence[float]) -> list[float]:
    """단위 길이로 만든다. 정규화된 벡터끼리는 **코사인 유사도 = 내적**이라
    유사도 계산이 행렬곱 한 번으로 끝난다.

    영벡터는 정규화할 수 없다. 조용히 통과시키면 그 항목과의 유사도가 항상 0이 되어
    코퍼스에서 사라진 것과 같아진다 — 조용한 소실이라 아무도 눈치채지 못한다.
    """
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        raise EmbeddingError("영벡터는 정규화할 수 없다 (임베딩이 비어 있음)")
    return [x / norm for x in vec]


def check_norm_canary(vecs: Sequence[Sequence[float]]) -> float | None:
    """들어온 벡터가 **이미** 단위 길이였는지 본다. 어긋난 값이 있으면 그 노름을 돌려준다.

    이건 정확성 장치가 아니다 — 어차피 우리가 다시 정규화하므로 결과는 같다.
    **모델이나 엔드포인트가 바뀐 것을 잡는 카나리**다.

    `/api/embed`(현행)는 L2 정규화된 벡터를 주지만 `/api/embeddings`(구 엔드포인트)는
    그렇지 않고, D-043의 폴백 경로로 경량 모델에 갈아탈 때도 보장이 없다.
    카나리가 없으면 그 전환이 **조용히** 일어나고, 우리는 정규화를 하고 있으니
    코사인 점수는 계속 그럴듯한 값이 나온다. 그럴듯한데 다른 모델의 값이다.
    D-036이 "실행 중 코드 지문 보고"를 만든 것과 같은 동기다.
    """
    for v in vecs:
        norm = math.sqrt(sum(x * x for x in v))
        if abs(norm - 1.0) > NORM_TOLERANCE:
            return norm
    return None


class OllamaEmbedder(Embedder):
    """Ollama HTTP + bge-m3 (D-043).

    `scripts/embed_latency.py`와 같은 엔드포인트·같은 응답 필드를 쓴다
    (`POST /api/embed`, `body["embeddings"]`). 두 곳이 갈라지면 지연 사전 게이트가
    실제 경로와 다른 것을 재게 된다.

    `httpx.AsyncClient`를 **주입받는다.** main.py가 이미 앱 수명 동안 클라이언트 하나를
    재사용하는 관례를 쓴다 — 요청마다 새로 만들면 매번 TCP 핸드셰이크가 붙어
    EVAL 4절 p95 예산을 혼자 까먹는다.
    """

    name = "ollama"

    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str = "bge-m3",
        endpoint: str = "http://localhost:11434",
        *,
        strict_norm: bool = True,
        owns_client: bool = False,
    ) -> None:
        self.client = client
        self.owns_client = owns_client
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.strict_norm = strict_norm
        self.dim: int | None = None          # 첫 호출에서 관측해 고정한다
        self.observed_norm: float | None = None   # 카나리가 본 마지막 이상 노름

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        if any(not isinstance(t, str) for t in texts):
            raise EmbeddingError("embed()는 문자열만 받는다")

        try:
            resp = await self.client.post(
                f"{self.endpoint}/api/embed",
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as e:
            # 원문을 예외 메시지에 넣지 않는다(D-029 — 본문 원문 미기록).
            raise EmbeddingError(f"Ollama 임베딩 실패 ({type(e).__name__}): {e}") from e
        except ValueError as e:
            raise EmbeddingError(f"Ollama 응답이 JSON이 아니다: {e}") from e

        vecs = body.get("embeddings")
        if not isinstance(vecs, list) or len(vecs) != len(texts):
            # 개수가 어긋나면 어느 벡터가 어느 문장인지 알 수 없다.
            # 순서가 밀린 채로 진행하면 최근접 항목 ID가 통째로 거짓말이 된다.
            raise EmbeddingError(
                f"임베딩 개수 불일치: 요청 {len(texts)}건, 응답 "
                f"{len(vecs) if isinstance(vecs, list) else type(vecs).__name__}건"
            )

        dims = {len(v) for v in vecs}
        if len(dims) != 1:
            raise EmbeddingError(f"한 응답 안에 차원이 섞여 있다: {sorted(dims)}")
        dim = dims.pop()
        if self.dim is None:
            self.dim = dim
        elif dim != self.dim:
            # 모델이 바뀌었거나 다른 모델이 응답했다. 1024 → 384는 all-minilm이다.
            raise EmbeddingError(f"차원이 바뀌었다: {self.dim} → {dim} (모델 교체 의심)")

        bad = check_norm_canary(vecs)
        if bad is not None:
            self.observed_norm = bad
            msg = (f"임베딩이 단위 길이가 아니다 (노름 {bad:.6f}). "
                   f"엔드포인트나 모델이 바뀌었을 수 있다 — model={self.model}")
            if self.strict_norm:
                raise EmbeddingError(msg)

        return [l2_normalize(v) for v in vecs]

    async def aclose(self) -> None:
        """**만든 사람이 닫는다.** 테스트는 클라이언트를 주입하고 스스로 닫으므로
        여기서 닫으면 안 된다. main.py의 팩토리만 owns_client=True로 만든다."""
        if self.owns_client:
            await self.client.aclose()


class FakeEmbedder(Embedder):
    """테스트용. **점수를 내가 정하기 위한** 임베더다 (D-043 설계 요건).

    문장 → 벡터를 직접 지정한다. 그래야 "T 바로 아래", "T 바로 위", "두 항목이 동점"
    같은 경계 상황을 **원해서** 만들 수 있다. 진짜 임베더로는 나온 값을 읽을 수만 있고,
    그러면 단언문이 "나온 값이 나왔다"가 되어 로직이 망가져도 통과한다.

    등록되지 않은 문장은 `default`를 쓴다. `default=None`이면 예외를 던진다 —
    **테스트가 의도하지 않은 문장을 임베딩하려 할 때 조용히 넘어가지 않게** 하기 위해서다.
    조용한 기본값은 "무엇을 재고 있는지 모르는 테스트"를 만든다.

        emb = FakeEmbedder({"공격 문장": [1.0, 0.0], "정상 문장": [0.0, 1.0]})
        # 코사인 유사도 0 — 완전히 다른 방향

    벡터는 여기서도 정규화된다. 테스트에서 `[3.0, 4.0]`처럼 편하게 써도 되고,
    **정규화 경로가 프로덕션과 같다**는 뜻이기도 하다.
    """

    name = "fake"

    def __init__(
        self,
        vectors: dict[str, Sequence[float]] | None = None,
        *,
        default: Sequence[float] | None = None,
    ) -> None:
        self.vectors = {k: list(v) for k, v in (vectors or {}).items()}
        self.default = list(default) if default is not None else None
        self.calls: list[list[str]] = []   # 몇 번, 무엇을 임베딩했는지 확인용

    def add(self, text: str, vec: Sequence[float]) -> "FakeEmbedder":
        self.vectors[text] = list(vec)
        return self

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        self.calls.append(texts)
        out: list[list[float]] = []
        for t in texts:
            v = self.vectors.get(t, self.default)
            if v is None:
                raise EmbeddingError(
                    f"FakeEmbedder에 등록되지 않은 문장이다(길이 {len(t)}자). "
                    "테스트가 의도한 입력만 임베딩하는지 확인할 것"
                )
            out.append(l2_normalize(v))

        dims = {len(v) for v in out}
        if len(dims) > 1:
            # 실제 임베더에서는 있을 수 없는 상황이다. fake가 프로덕션보다 관대하면
            # 테스트가 통과하는 코드가 프로덕션에서 깨진다.
            raise EmbeddingError(f"FakeEmbedder 벡터 차원이 섞여 있다: {sorted(dims)}")
        return out
