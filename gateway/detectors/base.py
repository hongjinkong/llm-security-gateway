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
from typing import Any


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

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답을 돌려보내기 직전에 불린다. 바꿀 게 없으면 None.

        요청은 앞에서 뒤로, 응답은 뒤에서 앞으로 지나간다(양파 껍질).
        들어올 때 마스킹한 검사기가 나갈 때 복원하는 짝이 맞아야 하기 때문이다.
        """
        return None
