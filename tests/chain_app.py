"""테스트 전용 앱 — 게이트웨이에 시험용 검사기를 등록한 뒤 그대로 노출한다.

이 검사기들은 gateway 패키지에 넣지 않는다. 테스트 더미가 배포 코드에 섞이면
"실제로 뭘 막고 있는가"가 흐려진다.
"""
from __future__ import annotations

from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.main import DETECTOR_REGISTRY, app  # noqa: F401  (uvicorn이 app을 가져간다)


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


DETECTOR_REGISTRY["test_block"] = AlwaysBlockOnMarker
DETECTOR_REGISTRY["test_mask"] = MaskSecret
DETECTOR_REGISTRY["test_boom"] = Exploding
