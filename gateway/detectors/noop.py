"""아무 판단도 하지 않는 검사기.

쓸모없어 보이지만 4-C의 목적 그 자체다. 체인에 검사기를 꽂아도
패스스루 동작이 바뀌지 않는다는 것을, 실제 PII 로직을 넣기 전에 증명한다.
배선과 로직을 분리해서 검증하면 4-D에서 문제가 생겼을 때 원인이 하나로 좁혀진다.
"""
from __future__ import annotations

from gateway.detectors.base import Detector, Inspection, Verdict


class NoOpDetector(Detector):
    def __init__(self, name: str = "noop") -> None:
        self.name = name

    async def inspect(self, insp: Inspection) -> Verdict:
        return Verdict.allow(self.name)
