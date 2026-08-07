"""4-C 검증: 검사기 계약(Verdict)과 체인 실행기 — 서버 없이 순수 단위 테스트."""
from __future__ import annotations

import pytest

from gateway.chain import DetectorChain
from gateway.detectors.base import Action, Detector, Inspection, Verdict
from gateway.detectors.noop import NoOpDetector

INSP = Inspection(request_id="r1", method="POST", path="/chat", headers={}, body=b"hello SECRET")


class Mask(Detector):
    name = "mask"

    async def inspect(self, insp):
        if b"SECRET" not in insp.body:
            return Verdict.allow(self.name)
        return Verdict.transform(self.name, insp.body.replace(b"SECRET", b"[MASKED]"), "마스킹")


class Block(Detector):
    name = "block"

    async def inspect(self, insp):
        return Verdict.block(self.name, "차단 사유")


class Spy(Detector):
    """자기가 본 본문을 기록한다. 순서·전달 검증용."""
    name = "spy"

    def __init__(self):
        self.seen: list[bytes] = []

    async def inspect(self, insp):
        self.seen.append(insp.body)
        return Verdict.allow(self.name)


class Boom(Detector):
    name = "boom"

    async def inspect(self, insp):
        raise RuntimeError("검사기 내부 버그")


# ---------- Verdict 계약 ----------

def test_transform_requires_body():
    with pytest.raises(ValueError):
        Verdict(Action.TRANSFORM, "d")


def test_non_transform_rejects_body():
    with pytest.raises(ValueError):
        Verdict(Action.BLOCK, "d", "reason", b"x")


# ---------- 체인 동작 ----------

@pytest.mark.anyio
async def test_empty_chain_is_identity():
    """검사기 0개 = 4-A와 완전히 동일. 기본 구성이 동작을 바꾸지 않는다."""
    r = await DetectorChain().run(INSP)
    assert r.body == INSP.body
    assert r.blocked is False and r.transformed is False and r.steps == []


@pytest.mark.anyio
async def test_noop_chain_is_identity():
    r = await DetectorChain([NoOpDetector("a"), NoOpDetector("b")]).run(INSP)
    assert r.body == INSP.body
    assert r.blocked is False and r.transformed is False
    assert [s.detector for s in r.steps] == ["a", "b"]
    assert all(s.action == "allow" for s in r.steps)


@pytest.mark.anyio
async def test_transform_is_applied_and_passed_downstream():
    """뒤 검사기는 '마스킹된 본문'을 본다. 그래서 검사기 순서가 결과를 바꾼다."""
    spy = Spy()
    r = await DetectorChain([Mask(), spy]).run(INSP)
    assert r.body == b"hello [MASKED]"
    assert r.transformed is True
    assert spy.seen == [b"hello [MASKED]"]


@pytest.mark.anyio
async def test_block_stops_the_chain_early():
    spy = Spy()
    r = await DetectorChain([NoOpDetector("first"), Block(), spy]).run(INSP)
    assert r.blocked is True and r.blocked_by == "block" and r.reason == "차단 사유"
    assert spy.seen == [], "차단 이후 검사기가 실행됐다 — 조기 종료 실패"
    assert [s.detector for s in r.steps] == ["first", "block"]


@pytest.mark.anyio
async def test_steps_record_per_detector_time():
    """EVAL 4절: 검사기 단계별 소요 시간을 개별 기록해야 병목을 찾을 수 있다."""
    r = await DetectorChain([NoOpDetector("a"), Mask()]).run(INSP)
    assert len(r.steps) == 2
    assert all(s.ms >= 0 for s in r.steps)
    assert r.chain_ms >= sum(s.ms for s in r.steps) - 0.001


@pytest.mark.anyio
async def test_detector_exception_is_not_swallowed():
    """fail-open이면 방어가 꺼진 채 'ON'으로 측정된다. 시끄럽게 실패시킨다."""
    with pytest.raises(RuntimeError):
        await DetectorChain([Boom()]).run(INSP)


@pytest.fixture
def anyio_backend():
    return "asyncio"
