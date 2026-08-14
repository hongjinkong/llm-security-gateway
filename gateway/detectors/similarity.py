"""유사도 기반 인젝션 탐지기 — 5단계 2차. 설계 근거는 D-042~D-044, D-047.

1차 룰이 **블랙리스트를 든 문지기**라면, 2차는 **몽타주를 든 형사**다.
명단에 정확히 없어도 "이 얼굴 어디서 봤는데"가 된다 — 코퍼스 52장의 몽타주와 대조해
**가장 닮은 것과의 닮은 정도**를 재고, 그게 기준선 T를 넘으면 차단한다.

형사는 문지기보다 비싸다. 요청마다 임베딩 왕복 1회가 붙고, 1차 차단율이 낮아서
**사실상 100%의 요청에 이 비용이 붙는다**(D-043). 그래서 지연 예산 50ms가 걸려 있다.

**코퍼스가 곧 로직이다.** 1차는 코드가 로직이었지만 2차는 데이터가 로직이다.
무엇을 코퍼스에 넣었는지는 `gateway/data/CORPUS.md`에 있다.

--- 이 검사기가 둘로 나뉜 이유 (D-048) ---
**임계값 T는 아직 정해지지 않았다.** D-044가 절차만 동결했고 숫자는 캘리브레이션이
정한다. T 없이 돌아가는 검사기를 하나로 만들면 두 가지 실패가 생긴다.
  - 기본값 T를 박으면 → 동결되지 않은 T로 측정해 EVAL 5.2 행을 채울 수 있다.
  - 조용히 통과시키면 → **방어가 꺼진 채로 "방어 ON" 측정**이 된다. 가장 나쁜 실패다.

그래서 이름을 둘로 나눴다.
  `injection_similarity`          T 필수. 없으면 **기동 실패**. 실제 방어.
  `injection_similarity_observe`  절대 차단하지 않고 점수만 로깅. 캘리브레이션용.

이름이 갈리면 `GATEWAY_DETECTORS` 문자열 자체가 어느 쪽이 돌았는지를 기록한다 —
D-036의 실행 중 코드 지문 보고와 `scripts/verify_gateway.sh`가 그대로 잡는다.
"관찰 모드였는지"를 사람이 기억할 필요가 없어진다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.detectors.injection import user_text
from gateway.embedding import Embedder, EmbeddingError

CORPUS_PATH = Path(__file__).resolve().parents[1] / "data" / "injection_corpus.jsonl"

# 코퍼스 벡터가 단위 길이인지 확인할 때 쓰는 허용 오차. float32 누적 오차만 허용한다.
CORPUS_NORM_TOLERANCE = 1e-3


class CorpusError(RuntimeError):
    """코퍼스를 읽거나 임베딩하지 못했다. **기동을 실패시킨다.**

    코퍼스가 비면 최근접이 없어 모든 요청이 통과한다 — 검사기가 있는데 아무것도 안 하는
    상태다. 로그에는 'allow'만 남아서 정상처럼 보인다(D-030 fail-open 금지와 같은 이유).
    """


def load_corpus(path: Path = CORPUS_PATH) -> list[dict]:
    """코퍼스를 읽는다. 스키마는 CORPUS.md 1절.

    여기서 무결성을 다시 검사하지 않는다 — `tests/test_injection.py`의 코퍼스 보호
    테스트 4개가 이미 못 박고 있다. 런타임에 중복 검사를 두면 규칙이 두 곳에 살게 되고,
    한쪽만 고치는 사고가 난다.
    """
    if not path.exists():
        raise CorpusError(f"코퍼스 파일이 없다: {path}")
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise CorpusError(f"코퍼스가 비어 있다: {path}")
    missing = [i for i, r in enumerate(rows) if not r.get("text") or not r.get("id")]
    if missing:
        raise CorpusError(f"id 또는 text가 빈 행이 있다 (행 번호 {missing[:5]})")
    return rows


class InjectionSimilarityDetector(Detector):
    """코퍼스 최근접 유사도로 판정한다.

    `threshold=None` + `observe=False`는 **생성 시점에** 거부한다. `build_chain()`이
    `lifespan`에서 불리므로 게이트웨이가 기동하지 못하고, 잘못된 구성으로 측정이
    시작되는 일이 없다.
    """

    def __init__(
        self,
        embedder: Embedder,
        *,
        threshold: float | None = None,
        observe: bool = False,
        corpus_path: Path = CORPUS_PATH,
    ) -> None:
        if not observe and threshold is None:
            raise ValueError(
                "injection_similarity는 임계값 T가 필요하다. "
                "GATEWAY_SIMILARITY_T를 설정하거나, 캘리브레이션 중이라면 "
                "injection_similarity_observe를 쓸 것 (D-044: T는 측정 전에 동결한다)"
            )
        if threshold is not None and not (-1.0 <= threshold <= 1.0):
            raise ValueError(f"코사인 임계값은 -1~1 범위여야 한다: {threshold}")

        self.embedder = embedder
        self.threshold = threshold
        self.observe = observe
        self.corpus_path = corpus_path

        self.rows: list[dict] = []
        self.matrix: np.ndarray | None = None   # (N, D) float32, 행마다 단위 길이

    @property
    def name(self) -> str:  # type: ignore[override]
        return "injection_similarity_observe" if self.observe else "injection_similarity"

    # --- 수명주기 -------------------------------------------------------------

    async def prepare(self) -> None:
        """기동 시 1회. 코퍼스를 통째로 임베딩해 메모리에 올린다(D-043).

        지연 로딩을 하지 않는 이유: 첫 요청이 코퍼스 52건 임베딩을 혼자 뒤집어쓰고,
        그 요청이 지연 통계에 섞이면 p95가 오염된다. 측정 도구가 측정을 망친다.
        """
        self.rows = load_corpus(self.corpus_path)
        try:
            vecs = await self.embedder.embed([r["text"] for r in self.rows])
        except EmbeddingError as e:
            raise CorpusError(f"코퍼스 임베딩 실패: {e}") from e
        if len(vecs) != len(self.rows):
            raise CorpusError(f"코퍼스 {len(self.rows)}행인데 벡터가 {len(vecs)}개다")

        m = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(m, axis=1)
        if not np.allclose(norms, 1.0, atol=CORPUS_NORM_TOLERANCE):
            # 임베더가 정규화했어야 한다(D-047). 여기서 어긋나면 코사인이 아니라
            # 그냥 내적이 되고, 점수가 그럴듯한데 틀린 값이 된다.
            raise CorpusError(
                f"코퍼스 벡터가 단위 길이가 아니다 (노름 범위 "
                f"{norms.min():.6f}~{norms.max():.6f})"
            )
        self.matrix = m

    async def aclose(self) -> None:
        self.rows = []
        self.matrix = None
        await self.embedder.aclose()

    # --- 판정 -----------------------------------------------------------------

    async def inspect(self, insp: Inspection) -> Verdict:
        if self.matrix is None:
            # prepare()를 안 부르고 요청이 들어왔다. 조용히 통과시키면 방어가 꺼진 채로
            # 측정이 돌아간다 — chain.py가 "가장 나쁜 실패"라고 부른 것.
            raise CorpusError(
                f"{self.name}: prepare()가 호출되지 않았다 (코퍼스 미적재)")

        text = user_text(insp.body).strip()
        if not text:
            # 빈 입력은 임베딩하지 않는다. 임베딩해도 의미가 없고, 모델에 따라
            # 영벡터가 나와 정규화가 터진다.
            return Verdict.allow(self.name, similarity_skipped="empty_input",
                                 mode=self._mode, threshold=self.threshold)

        vecs = await self.embedder.embed([text])   # 예외는 그대로 위로 (D-030)
        q = np.asarray(vecs[0], dtype=np.float32)
        if q.shape[0] != self.matrix.shape[1]:
            raise CorpusError(
                f"질의 벡터 차원 {q.shape[0]}이 코퍼스 {self.matrix.shape[1]}과 다르다 "
                "(모델 교체 의심)")

        scores = self.matrix @ q          # 단위 벡터끼리라 내적 = 코사인 유사도
        idx = int(np.argmax(scores))
        score = float(scores[idx])
        row = self.rows[idx]

        # D-044: **판정과 무관하게 전량 기록한다.** 그래야 측정 후 "T가 달랐다면"을
        # 재측정 없이 계산할 수 있다. 원문은 요청도 코퍼스도 남기지 않는다(D-029).
        meta = {
            "similarity": round(score, 6),
            "nearest_id": row["id"],
            "nearest_source": row.get("source", ""),
            "nearest_category": row.get("category", ""),
            "threshold": self.threshold,
            "mode": self._mode,
        }

        if self.observe or self.threshold is None or score < self.threshold:
            return Verdict.allow(self.name, **meta)

        # 차단 사유에 코퍼스 원문이나 어휘를 넣지 않는다 — 룰 역산 방지(D-040).
        # 응답에도 들어가지 않는다. main.py가 200 + 타겟 스키마로 덮는다.
        return Verdict.block(self.name, reason="유사도 임계값 초과", **meta)

    @property
    def _mode(self) -> str:
        return "observe" if self.observe else "enforce"


# --- 환경변수에서 만들기 --------------------------------------------------------

def threshold_from_env(env: dict[str, str] | None = None) -> float | None:
    """`GATEWAY_SIMILARITY_T`. 없으면 None(= enforce 모드에서 기동 실패).

    빈 문자열도 None으로 본다 — `GATEWAY_SIMILARITY_T=` 로 껐다고 생각하는 실수를
    "0.0으로 설정"으로 오독하면 **모든 요청이 차단**된다.
    """
    src = os.environ if env is None else env
    raw = (src.get("GATEWAY_SIMILARITY_T") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"GATEWAY_SIMILARITY_T가 숫자가 아니다: {raw!r}") from e
