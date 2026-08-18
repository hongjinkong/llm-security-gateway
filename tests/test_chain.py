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


class Note(Detector):
    """meta를 남기는 검사기. prior 전달 검증용."""

    def __init__(self, name: str, **meta):
        self.name = name
        self._meta = meta

    async def inspect(self, insp):
        return Verdict.allow(self.name, **self._meta)


class PriorSpy(Detector):
    """자기가 본 prior를 기록한다. **참조를 그대로 들고 있는다** — 스냅샷 검증용."""
    name = "prior_spy"

    def __init__(self, name: str = "prior_spy"):
        self.name = name
        self.seen: list = []          # 실행 시점에 복사한 것
        self.held: list = []          # 참조를 그대로 붙든 것

    async def inspect(self, insp):
        self.seen.append({k: dict(v) for k, v in insp.prior.items()})
        self.held.append(insp.prior)
        return Verdict.allow(self.name)


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


# ---------- prior: 앞 검사기의 meta를 뒤 검사기가 읽는다 (D-053) ----------
#
# 3차 LLM Judge가 2차 유사도 점수를 게이팅에 쓰기 위한 통로다(JUDGE_DESIGN 5.1).
# 없으면 Judge가 임베딩을 한 번 더 돌려야 하고 지연이 두 배가 된다.


@pytest.mark.anyio
async def test_first_detector_sees_empty_prior():
    """앞이 없으면 빈 메모판. 검사기가 `.get()`으로 안전하게 다룰 수 있어야 한다."""
    spy = PriorSpy()
    await DetectorChain([spy]).run(INSP)
    assert spy.seen == [{}]


@pytest.mark.anyio
async def test_prior_carries_earlier_detector_meta():
    spy = PriorSpy()
    await DetectorChain([Note("sim", similarity=0.71, nearest_id="K-R1-08"), spy]).run(INSP)
    assert spy.seen == [{"sim": {"similarity": 0.71, "nearest_id": "K-R1-08"}}]


@pytest.mark.anyio
async def test_detector_cannot_see_its_own_verdict_in_prior():
    """자기 판정은 자기가 볼 수 없다. 기록은 inspect가 끝난 뒤에 붙는다."""
    spy = PriorSpy("prior_spy")
    await DetectorChain([Note("a", x=1), spy, Note("z", y=2)]).run(INSP)
    assert "prior_spy" not in spy.seen[0]
    assert "z" not in spy.seen[0], "뒤 검사기의 판정이 미리 보인다 — 순서가 깨졌다"


@pytest.mark.anyio
async def test_prior_is_read_only():
    """검사기가 앞 단계 기록을 고칠 수 있으면 감사 로그를 믿을 수 없다."""
    spy = PriorSpy()
    await DetectorChain([Note("a", x=1), spy]).run(INSP)
    with pytest.raises(TypeError):
        spy.held[0]["a"] = {"x": 999}          # type: ignore[index]
    with pytest.raises(TypeError):
        spy.held[0]["a"]["x"] = 999            # type: ignore[index]


@pytest.mark.anyio
async def test_prior_is_a_snapshot_not_a_live_view():
    """**이 테스트가 이 기능의 핵심이다.**

    산 dict를 프록시로 감싸 넘기면, 뒤에 실행된 검사기의 meta가 앞 검사기가 붙들고 있던
    참조에도 나타난다. 그러면 "이 검사기가 무엇을 보고 판단했나"를 사후에 되짚을 수 없다.
    """
    spy = PriorSpy()
    await DetectorChain([Note("a", x=1), spy, Note("z", y=2)]).run(INSP)
    assert dict(spy.held[0]) .keys() == {"a"}, (
        f"실행 시점 이후의 판정이 새어 들어왔다: {dict(spy.held[0]).keys()}")


@pytest.mark.anyio
async def test_prior_and_transformed_body_arrive_together():
    """마스킹된 본문과 앞 단계 메모를 같은 Inspection에서 본다."""
    spy = PriorSpy()
    await DetectorChain([Note("a", x=1), Mask(), spy]).run(INSP)
    assert spy.seen == [{"a": {"x": 1}, "mask": {}}]


@pytest.mark.anyio
async def test_prior_does_not_change_existing_chain_behaviour():
    """additive임을 고정한다. prior를 안 보는 기존 검사기는 결과가 그대로여야 한다."""
    spy = Spy()
    r = await DetectorChain([Mask(), spy]).run(INSP)
    assert r.body == b"hello [MASKED]" and r.transformed is True
    assert spy.seen == [b"hello [MASKED]"]
