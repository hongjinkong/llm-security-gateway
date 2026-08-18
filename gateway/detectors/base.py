"""검사기 인터페이스 — 모든 방어 컴포넌트가 따르는 계약.

설계의 출발점은 코드가 아니라 EVAL_CRITERIA다. EVAL 3.2가 오탐을
'정상 / 부분 저하 / 차단' 세 등급으로 나누라고 동결해 놓았으므로,
검사기가 반환할 수 있는 판정도 정확히 그 셋이어야 한다.
등급이 코드에 없으면 FPR을 그 기준으로 집계할 수 없다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

# 앞 검사기가 아무것도 안 남겼을 때의 기본값.
#
# `default_factory`를 쓰는 이유: dataclasses는 기본값의 **타입**이 unhashable이면
# ('mappingproxy'가 그렇다) 가변 기본값으로 보고 ValueError를 던진다. 실제로는 읽기
# 전용이라 인스턴스끼리 공유해도 안전하므로, 팩토리가 매번 **같은 객체**를 돌려준다.
NO_PRIOR: Mapping[str, Mapping[str, Any]] = MappingProxyType({})


def _no_prior() -> Mapping[str, Mapping[str, Any]]:
    return NO_PRIOR


class Action(StrEnum):
    """검사기가 내릴 수 있는 판정. EVAL 3.2의 3단계 분류와 1:1 대응한다.

    ALLOW     → "정상"      FPR 집계 미포함
    TRANSFORM → "부분 저하"  FPR 0.5 가중 (마스킹 등으로 응답 품질만 저하)
    BLOCK     → "차단"      FPR 1.0 가중 (응답 거부)
    """

    ALLOW = "allow"
    TRANSFORM = "transform"
    BLOCK = "block"


@dataclass(frozen=True)
class Inspection:
    """검사기에게 보여주는 요청 스냅샷. 검사기는 이걸 변경하지 않는다."""

    request_id: str
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes
    session: str = ""    # 마스킹 매핑을 묶는 키. 비어 있으면 검사기가 알아서 정한다.

    # 앞에서 이미 판정을 끝낸 검사기들의 meta. {검사기 이름: meta}. **읽기 전용이다.**
    #
    # 왜 필요한가 (D-053 / JUDGE_DESIGN 5.1): 3차 LLM Judge는 2차가 계산한 유사도
    # 점수를 게이팅에 쓴다. 이 통로가 없으면 Judge가 임베딩을 한 번 더 돌려야 하고,
    # 임베딩 왕복이 2회가 되어 지연이 두 배가 된다.
    #
    # 왜 meta만 넘기고 Verdict 전체를 안 넘기는가: BLOCK은 조기 종료라 뒤 검사기가
    # 아예 실행되지 않는다. 따라서 여기 담기는 것은 항상 ALLOW 또는 TRANSFORM의
    # meta뿐이고, action을 넘겨도 읽는 쪽이 쓸 일이 없다. 좁게 연다.
    #
    # 원문은 담기지 않는다 — meta에 원문을 넣지 않는 것이 기존 규칙이다(D-029).
    prior: Mapping[str, Mapping[str, Any]] = field(default_factory=_no_prior)


@dataclass(frozen=True)
class Verdict:
    """검사기 1개의 판정 결과."""

    action: Action
    detector: str
    reason: str = ""
    body: bytes | None = None            # TRANSFORM일 때만 채운다
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action is Action.TRANSFORM and self.body is None:
            raise ValueError(f"{self.detector}: TRANSFORM은 바뀐 body를 반드시 반환해야 한다")
        if self.action is not Action.TRANSFORM and self.body is not None:
            raise ValueError(f"{self.detector}: TRANSFORM이 아니면 body를 반환하지 않는다")

    @staticmethod
    def allow(detector: str, **meta: Any) -> "Verdict":
        return Verdict(Action.ALLOW, detector, meta=meta)

    @staticmethod
    def transform(detector: str, body: bytes, reason: str = "", **meta: Any) -> "Verdict":
        return Verdict(Action.TRANSFORM, detector, reason, body, meta)

    @staticmethod
    def block(detector: str, reason: str, **meta: Any) -> "Verdict":
        return Verdict(Action.BLOCK, detector, reason, meta=meta)


class Detector(ABC):
    """모든 검사기의 부모. 이름 하나와 inspect 하나만 있으면 된다.

    async인 이유: 5단계의 LLM Judge는 외부 모델을 호출한다.
    지금 동기로 만들면 그때 인터페이스 전체를 갈아엎어야 한다.
    """

    name: str = "unnamed"

    @abstractmethod
    async def inspect(self, insp: Inspection) -> Verdict:
        """요청을 보고 판정을 돌려준다. 예외를 삼키지 않는다(체인 정책 참조)."""
        raise NotImplementedError

    async def prepare(self) -> None:
        """기동 시 1회. 무거운 준비를 여기서 한다 — 5단계 2차의 코퍼스 임베딩(D-043).

        지연 로딩을 쓰지 않는 이유: 첫 요청이 준비 비용을 혼자 뒤집어쓰고, 그 요청이
        지연 통계에 섞이면 p95가 오염된다. 측정 도구가 측정을 망친다.

        기본 구현은 아무것도 하지 않는다 — 기존 검사기는 영향받지 않는다.
        """
        return None

    async def aclose(self) -> None:
        """종료 시 1회. prepare()에서 연 자원을 닫는다. 기본은 아무것도 하지 않는다."""
        return None

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답을 돌려보내기 직전에 불린다. 바꿀 게 없으면 None.

        요청은 앞에서 뒤로, 응답은 뒤에서 앞으로 지나간다(양파 껍질).
        들어올 때 마스킹한 검사기가 나갈 때 복원하는 짝이 맞아야 하기 때문이다.
        """
        return None
