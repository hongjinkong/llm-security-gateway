"""카나리 관측 검사기 — 6단계 출력 방어. **관측형이다.**

설계 본문: docs/CANARY_DESIGN.md (2026-08-19 동결). 근거: DECISIONS.md D-058.

하는 일은 하나뿐이다. 타겟이 낸 응답에 카나리 토큰 세 종류가 각각 몇 번
나오는지 세어 감사 로그에 남긴다. **응답은 바꾸지 않는다.**

하지 않는 일을 적어둔다 — 이 목록이 이 파일의 정의다.

  * 응답을 바꾸지 않는다. 차단·삭제·재작성 전부 없다.
    차단형은 D-059로 보류됐고, 응답 경로에는 애초에 차단을 담을 자리가 없다
    (`on_response`의 반환형에 Action이 없다).
  * 요청 경로에 개입하지 않는다. `inspect`는 항상 ALLOW이고 meta도 안 남긴다.
    meta를 남기면 `Inspection.prior`를 통해 뒤 검사기의 판단 재료가 된다(D-053).
  * 값을 로그로 내보내지 않는다. meta는 종류와 횟수뿐이다(R4 / D-029).
  * 환경변수를 스스로 읽지 않는다. 값은 생성자로 주입받는다.
    배선은 gateway/main.py가 하고, 이 파일은 값의 출처를 모른다.
  * 값을 소스에 담지 않는다(R2 / EVAL 2.3b).

왜 응답을 바꾸면 안 되는가 (D-058 1절 근거 B):
    EVAL 2.3(b)에서 카나리는 ASR 채점기다. 출력에서 카나리를 지우거나 그걸로
    차단하면 방어 ON 구성의 카나리 검출률은 구조적으로 0이 된다.

        ASR_canary(OFF) = 측정값
        ASR_canary(ON)  = 0        <- 측정이 아니라 정의다

    집계 규칙이면 되돌릴 수 있지만 이건 배선이라 원자료가 아예 생성되지 않는다.
    자기가 재는 신호를 자기가 지우면 그 신호로는 자기를 평가할 수 없다.

왜 정규식이 아니라 정확한 값으로 세는가:
    세 토큰은 형식이 같다. 형식으로 매칭하면 종류를 구분하지 못하고, 그것이
    D-058이 후보 (f)를 기각한 사유다(EVAL 2.5는 종류별 분리 기록을 요구한다).
    정확한 값으로 세면 "형식만 같은 남의 문자열"을 세지 않는 성질이 덤으로 따라온다.
"""
from __future__ import annotations

from collections.abc import Sequence

from gateway.detectors.base import Detector, Inspection, Verdict

NAME = "canary_observe"

# meta 키이자 종류 이름. 순서가 감사 로그의 필드 순서가 된다.
KINDS = ("canary_a", "canary_b", "canary_doc")


class CanaryWiringError(RuntimeError):
    """배선이 틀렸다. **기동을 실패시킨다.**

    `JudgeWiringError`와 같은 성격이다 — 판정 실패가 아니라 구성 오류이며,
    삼키면 관측값이 조용히 틀린 채로 D-059의 입력이 된다.
    """


class CanaryMissingError(CanaryWiringError):
    """값이 없다 (R3)."""


class CanaryCollisionError(CanaryWiringError):
    """값이 서로 겹친다 (2026-08-21 보강).

    **왜 `CanaryMissingError`와 타입을 나누는가** (2026-08-21, 변이 검사가 드러냈다):

    둘 다 `RuntimeError`로 던지면 두 분기가 서로를 가려준다. `prepare()`의 값 존재
    검사를 없앤 변이(M2)를 걸었을 때, 세 값이 전부 `None`인 케이스는 여기 중복값
    검사에 걸려 여전히 `RuntimeError`를 냈고, 그래서 **그 테스트가 통과했다.**
    변이는 나머지 4개가 잡았지만 그 파라미터는 아무것도 지키지 않고 있었다.

    타입을 나누면 각 분기를 독립적으로 시험할 수 있다.

    > **변이 검사는 잡혔나/안 잡혔나만이 아니라 몇 개가 잡혔는지를 봐야 한다.**
    """


def validate_canary_position(names: Sequence[str]) -> None:
    """`canary_observe`가 있으면 **목록 맨 뒤**여야 한다 (설계 4-1).

    `build_chain()`이 부르고, 그것이 `lifespan`에서 불리므로 **게이트웨이가
    기동하지 못한다.** `injection_similarity`가 T 없이, `injection_judge`가
    앞의 `observe` 없이 못 뜨는 것과 같은 장치다(D-048 / D-054).

    `DetectorChain.run_response()`는 검사기를 역순으로 지난다. 목록 맨 뒤에
    있어야 응답 경로에서 맨 앞이 되고, **타겟이 낸 원본을 아무도 손대기 전에
    본다.**

    **지금은 위치를 틀려도 숫자가 안 바뀐다.** 응답 경로에서 텍스트를 바꾸는
    검사기는 `pii_mask`의 복원 하나뿐이고 그것은 볼트 토큰만 되돌린다. 그래서
    이 검사는 오늘의 숫자를 지키는 것이 아니라 **D-059가 차단형이나 출력
    재작성을 여는 시점**을 지킨다. 그때 카나리가 방어 뒤에 놓이면 방어가 손댄
    뒤의 텍스트를 관측하게 되고, 그것이 D-058이 *"방어가 판정기를 먹는다"*고
    부른 상태다. 규칙이 필요해지는 시점과 규칙을 잊기 쉬운 시점이 같다.

    범위를 좁게 잡는다 — "있으면 맨 뒤" 하나뿐이고 일반적인 순서 규칙을
    만들지 않는다. 규칙이 넓어지면 그 자체가 다음 결정의 제약이 된다.

    2026-08-21 보강. 설계 4-1은 이 위치를 *권고 이유*로 적었지 위반 시 기동
    실패로 적지 않았다. 사용자 승인 후 넣었다(D-058 이행 기록에 남긴다).
    """
    if NAME not in names:
        return
    if names[-1] != NAME:
        raise CanaryWiringError(
            f"{NAME}는 GATEWAY_DETECTORS 맨 뒤여야 한다 (응답 경로 맨 앞 = 타겟 원본). "
            f"현재 구성: {list(names)}. 뒤에 다른 검사기가 있으면 그 검사기가 응답을 "
            f"바꾼 뒤의 텍스트를 관측하게 되고, 관측값이 방어 구성에 의존하게 된다 "
            f"(docs/CANARY_DESIGN.md 4-1)")


class CanaryObserveDetector(Detector):
    name = NAME

    def __init__(self, canary_a: str | None, canary_b: str | None,
                 canary_doc: str | None) -> None:
        # **생성자는 검증하지 않는다.** 검증은 prepare()에서 한다.
        # DetectorChain.prepare()가 lifespan에서 불리므로, 거기서 던져야
        # "게이트웨이가 기동하지 않는다"가 된다(D-043 / D-048과 같은 자리).
        self._tokens: dict[str, str | None] = dict(
            zip(KINDS, (canary_a, canary_b, canary_doc)))

    async def prepare(self) -> None:
        """배선이 성립하는지 확인한다. 아니면 기동을 실패시킨다 (R3).

        값이 안 넘어온 채 관측이 돌면 검출률이 조용히 0이 되고, "관측했는데
        아무것도 안 나왔다"는 거짓 기록이 남는다. 그 기록은 D-059의 FP 바닥값이
        되어 차단형 성립 판정까지 오염시킨다.

        검사 둘:

        (1) 세 값이 다 있는가. 빈 문자열도 '없음'으로 본다 — compose의
            `${...:?}`가 먼저 막지만, 맥북에서 uvicorn을 직접 띄우는 경로에는
            그 방어가 없다.

        (2) 세 값이 서로 다른가. **설계 4-2에는 없는 검사다**(2026-08-21 보강).
            값이 겹치면 같은 등장을 두 칸에 각각 세게 되어 EVAL 2.5가 요구한
            종류별 분리 집계가 조용히 무의미해진다. 관측은 돌고 숫자도 나오므로
            겉으로는 정상이며, V1의 지문 대조도 세 값을 묶어 해싱하기 때문에
            이 경우를 잡지 못한다. 근거는 (1)과 같다 — 조용히 틀린 숫자를 내는
            상태보다 기동 실패가 낫다.

        예외 문구에 **값은 넣지 않는다** — 기동 실패 로그도 로그다(D-029).
        """
        missing = [k for k, v in self._tokens.items() if not v]
        if missing:
            raise CanaryMissingError(
                f"{self.name}: 카나리 값이 비어 있다 ({', '.join(missing)}). "
                f"GATEWAY_CANARY_A / _B / _DOC 를 .env에서 넘겨야 한다 "
                f"(docs/CANARY_DESIGN.md 3-2). 값 없이 관측하면 검출률이 조용히 "
                f"0이 되고 그 0이 D-059의 입력이 된다 — 그래서 기동을 실패시킨다")

        by_value: dict[str, list[str]] = {}
        for kind, token in self._tokens.items():
            by_value.setdefault(token, []).append(kind)   # type: ignore[arg-type]
        collided = [ks for ks in by_value.values() if len(ks) > 1]
        if collided:
            pairs = " / ".join(" == ".join(ks) for ks in collided)
            raise CanaryCollisionError(
                f"{self.name}: 카나리 값이 서로 겹친다 ({pairs}). 종류별 분리 집계가 "
                f"불가능하다 — 같은 등장을 두 칸에 각각 세게 된다(EVAL 2.5). "
                f"관측은 돌고 숫자도 나오므로 겉으로는 정상이고 지문 대조로도 "
                f"안 잡힌다. 그래서 기동을 실패시킨다")

    async def inspect(self, insp: Inspection) -> Verdict:
        """요청 경로에서는 아무것도 하지 않는다. 본문을 읽지도 않는다."""
        return Verdict.allow(self.name)

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답에 카나리가 몇 번 나오는지 센다. **text는 그대로 돌려준다.**

        `gateway/main.py`가 `restored != text`일 때만 본문을 교체하므로, 입력과
        같은 객체를 돌려주면 응답 바이트가 그대로 보존된다.

        전부 0이면 None을 돌려준다 — 감사 로그의 `response_detectors`가
        0건 줄로 불어나지 않게 한다(설계 4-3).

        **세는 범위 = 응답 본문 전체다** (2026-08-21 결정, 사용자 승인).

        `gateway/main.py`가 넘기는 `text`는 `textResponse` 필드가 아니라 응답
        JSON을 통째로 디코딩한 문자열이다. 그 결과 평가 쪽과 자가 다르다.

            eval/canary_fpr.py · eval/fpr_run.py · garak    textResponse 한 필드
            canary_observe (여기)                            본문 전체

        범위를 이렇게 정한 근거: 차단형이 실제로 보게 될 것 — 사용자에게 나가는
        응답 전체 — 과 일치한다. 관측값의 첫 용도가 차단형 성립 판정용 FP
        바닥값이므로(설계 7절 ①) 그쪽에 자를 맞춘다.

        **대가를 적어둔다.** 설계 5-2의 V3(관측 건수 vs 리포트 독립 집계)는 두
        출처가 같은 것을 셀 때만 성립한다. 이 선택으로 V3는 대조 불가가 되며,
        설계가 그 경우를 이미 열어 뒀다 — *"독립 출처 없으면 '대조 불가'로 기록"*.
        관측값으로 EVAL 2.5의 판정을 대체하지 않는다는 7절 원칙은 그대로다.

        **미확인 하나**: 실제 타겟 응답의 `sources`에 문서 청크 본문이 실리면
        DOC 카나리가 11개 절 푸터 전부에 있으므로 정상 질문에서도 매번 검출되어
        k(설계 5-1)가 구조적으로 커진다. 저장소에 원본 본문이 남아 있지 않아
        확인하지 못했다. **빚 7 관측 런 전에 응답 1건으로 확인할 것.**

        토큰이 None인 경우는 prepare()가 이미 막았다.
        """
        counts = {kind: text.count(token) for kind, token in self._tokens.items()}
        if not any(counts.values()):
            return None
        return text, counts
