"""검사기 체인 실행기 — 검사기들을 순서대로 돌리고 결과를 합친다.

공항 보안검색 비유: 신분증 확인 → X-ray → 금속탐지기를 차례로 통과한다.
각 검색대는 통과시키거나(ALLOW), 라이터만 압수하고 보내거나(TRANSFORM),
탑승을 거부한다(BLOCK). 거부가 나오면 뒤 검색대는 볼 필요가 없다 — 조기 종료.

TRANSFORM은 다음 검사기에게 '바뀐 본문'을 넘긴다. 마스킹 후의 요청을
인젝션 탐지기가 보게 되므로, 검사기 순서가 결과를 바꾼다.

예외 정책: 검사기가 던진 예외를 삼키지 않는다.
  - 삼키고 통과시키면(fail-open) 방어가 꺼진 채로 "방어 ON" 측정이 되어
    리포트가 거짓말을 한다. 이 프로젝트에서 가장 나쁜 실패다.
  - 삼키고 차단하면(fail-closed) 버그 하나가 전체 요청을 막아 FPR이 폭발한다.
  - 그래서 그대로 올려보내 500으로 터뜨린다. 시끄럽게 실패하는 쪽이 안전하다.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from gateway.detectors.base import Action, Detector, Inspection


@dataclass(frozen=True)
class Step:
    """검사기 1개의 실행 기록. EVAL 4절 '검사기 단계별 소요 시간(병목 식별용)'."""

    detector: str
    action: str
    ms: float
    reason: str = ""
    meta: dict = field(default_factory=dict)   # 검사기가 남긴 부가정보(원문 값은 금지)

    def as_dict(self) -> dict:
        d = {"detector": self.detector, "action": self.action, "ms": self.ms}
        if self.reason:
            d["reason"] = self.reason
        if self.meta:
            d.update(self.meta)
        return d


@dataclass
class ChainResult:
    body: bytes                       # 최종 본문 (TRANSFORM이 있었으면 바뀐 것)
    blocked: bool = False
    blocked_by: str | None = None
    reason: str = ""
    steps: list[Step] = field(default_factory=list)
    chain_ms: float = 0.0
    transformed: bool = False


class DetectorChain:
    def __init__(self, detectors: Sequence[Detector] = ()) -> None:
        self.detectors = tuple(detectors)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.detectors)

    async def run(self, insp: Inspection) -> ChainResult:
        body = insp.body
        steps: list[Step] = []
        transformed = False
        t_chain = time.perf_counter()

        for det in self.detectors:
            current = replace(insp, body=body)
            t0 = time.perf_counter()
            verdict = await det.inspect(current)   # 예외는 그대로 위로 올린다
            ms = round((time.perf_counter() - t0) * 1000, 3)
            steps.append(Step(det.name, str(verdict.action), ms, verdict.reason, verdict.meta))

            if verdict.action is Action.BLOCK:
                return ChainResult(
                    body=body, blocked=True, blocked_by=det.name, reason=verdict.reason,
                    steps=steps, chain_ms=round((time.perf_counter() - t_chain) * 1000, 3),
                    transformed=transformed,
                )
            if verdict.action is Action.TRANSFORM:
                body = verdict.body            # type: ignore[assignment]
                transformed = True

        return ChainResult(
            body=body, steps=steps,
            chain_ms=round((time.perf_counter() - t_chain) * 1000, 3),
            transformed=transformed,
        )

    async def run_response(self, session: str, text: str) -> tuple[str, list[Step]]:
        """응답 후처리. 검사기를 역순으로 지나간다."""
        steps: list[Step] = []
        for det in reversed(self.detectors):
            t0 = time.perf_counter()
            out = await det.on_response(session, text)
            if out is None:
                continue
            text, meta = out
            steps.append(Step(det.name, "restore",
                              round((time.perf_counter() - t0) * 1000, 3), "", meta))
        return text, steps
