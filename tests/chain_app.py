"""테스트 전용 검사기 — 게이트웨이 레지스트리에 더한 사전(`REGISTRY`)을 make_stack에 넘긴다(D-118).

이 검사기들은 gateway 패키지에 넣지 않는다. 테스트 더미가 배포 코드에 섞이면
"실제로 뭘 막고 있는가"가 흐려진다.
"""
from __future__ import annotations

from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.settings import DETECTOR_REGISTRY


class NoOpDetector(Detector):
    """아무 판단도 하지 않는 검사기 — 검사기를 꽂아도 중계가 바뀌지 않는다는 것을 배선만으로 보인다."""

    def __init__(self, name: str = "noop") -> None:
        self.name = name

    async def inspect(self, insp: Inspection) -> Verdict:
        return Verdict.allow(self.name)


class AlwaysBlockOnMarker(Detector):
    name = "test_block"

    async def inspect(self, insp: Inspection) -> Verdict:
        if b"BLOCKME" in insp.body:
            return Verdict.block(self.name, "테스트용 차단 규칙 일치")
        return Verdict.allow(self.name)


class MaskSecret(Detector):
    name = "test_mask"

    async def inspect(self, insp: Inspection) -> Verdict:
        if b"SECRET" not in insp.body:
            return Verdict.allow(self.name)
        return Verdict.transform(self.name, insp.body.replace(b"SECRET", b"[MASKED]"),
                                 "테스트용 마스킹")


class Exploding(Detector):
    name = "test_boom"

    async def inspect(self, insp: Inspection) -> Verdict:
        raise RuntimeError("검사기 내부 버그 재현")


REGISTRY = {**DETECTOR_REGISTRY, "noop": lambda s: NoOpDetector(), "test_block": lambda s: AlwaysBlockOnMarker(),
            "test_mask": lambda s: MaskSecret(), "test_boom": lambda s: Exploding()}
