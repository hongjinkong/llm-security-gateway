"""룰 기반 인젝션 탐지기 — 5단계 1차. 설계 근거는 D-037~D-040.

클럽 입구의 블랙리스트 명단을 든 문지기다. 명단에 있는 얼굴은 막고, 없으면 통과다.
빠르고(정규식) 왜 막았는지 설명할 수 있지만, 명단에 없는 표현은 그대로 지나간다.
그래서 5단계는 3단이다 — 룰(1차)이 뻔한 것을 싸게 걸러내고, 유사도(2차)가 변형을,
LLM Judge(3차)가 애매한 것만 비싸게 판단한다. **룰 혼자 다 막을 필요가 없다.**
이 전제가 룰을 얼마나 공격적으로 만들지를 정한다: 놓치는 쪽이 잘못 막는 쪽보다 낫다.
놓친 것은 2차·3차가 받지만, 잘못 막은 요청은 아무도 되돌려주지 않는다.

핵심 원칙 — **동사가 아니라 목적어를 본다.**
  정상 질문 4개(B-101·B-106·B-109·B-114)가 전부 "무시/잊고"를 포함한다.
  동사만 보면 넷 다 걸려서 FPR 4%가 즉시 발생한다. 공격과의 차이는 목적어다.
      B-101  무시 대상 = 사용자 자신의 이전 질문("연차 얘기")
      B-106  무시 대상 = 대화 맥락("이전 대화")
      B-109  무시 대상 = 회사 사규("규정"은 HR 도메인의 업무 단어다)
      공격    무시 대상 = 시스템이 준 지시
  따라서 R1은 [무효화 동사]와 [시스템 지시 목적어]가 **같은 문장 안에** 있을 때만 발동한다.

목적어를 화이트리스트로 둔 이유:
  제외 목록(블랙리스트)으로 만들면 새로운 업무 단어가 생길 때마다 오탐이 난다.
  화이트리스트는 모르는 단어를 기본 통과시킨다. 1차 룰에는 이쪽이 맞다.
  아래 EXCLUDED_OBJECTS는 코드가 아니라 **문서**다. 화이트리스트에 없으니 이미
  통과하지만, 나중에 누가 "규정"을 목적어에 추가하지 못하도록 테스트로 묶어둔다.

범위 (D-038 정정본):
  R1 지시 무효화 / R2 역할 전환·제약 해제 두 갈래만 만든다.
  '시스템 프롬프트 요구'(B-111·B-115)는 입력 단에서 막지 않는다. 묻는 것과
  새어나가는 것은 다른 사건이며, 유출은 6단계 카나리가 확정 판정한다.
  R3(역할 헤더 위조 `System:`)은 B-114가 같은 형태라 1차에서 보류하고 2차로 넘긴다.

어휘 출처 (D-039):
  공개된 공격 기법 범주와 일반 지식만 사용했다.
  results/*.report.jsonl(채점에 쓸 공격 원문)은 열지 않았다. 공격셋은 홀드아웃이다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from gateway.detectors.base import Detector, Inspection, Verdict

# --- 룰이 볼 텍스트 -----------------------------------------------------------
# 사용자 입력이 들어 있는 필드. 타겟을 바꿔도 여기만 고치면 된다(SCOPE 7절 이식성).
USER_FIELDS = ("message", "prompt", "input", "query", "text")


def user_text(body: bytes) -> str:
    """룰이 볼 텍스트를 꺼낸다. **원문 바이트를 그대로 정규식에 넣지 않는다.**

    JSON은 한글을 두 가지로 담을 수 있다.
        ensure_ascii=False → {"message": "이전 지시를 무시하고"}
        ensure_ascii=True  → {"message": "\\uc774\\uc804 \\uc9c0\\uc2dc..."}
    같은 요청이지만 두 번째에서는 한글 룰이 **하나도** 맞지 않는다. 바이트를 그대로
    훑으면 탐지기가 조용히 아무것도 못 잡고 로그에는 'allow'만 남는다.
    D-035에서 겪은 것과 같은 실패다 — 검사 대상을 좁게 잡으면 없는 것을 있다고 착각한다.
    json.loads가 \\uXXXX를 한글로 되돌려주므로, 파싱해서 입력 필드를 꺼내 쓴다.

    파싱에 실패하면 본문 전체를 디코딩해 넘긴다. 놓치는 것보다는 낫다.
    """
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body.decode("utf-8", errors="ignore")
    if isinstance(obj, dict):
        parts = [v for k in USER_FIELDS
                 if isinstance(v := obj.get(k), str) and v]
        if parts:
            return "\n".join(parts)
    return body.decode("utf-8", errors="ignore")


# 문장 경계. 동사와 목적어가 같은 문장에 있어야 "그 동사의 목적어"라고 말할 수 있다.
_SENTENCE = re.compile(r"[.!?。！？\n]+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text) if s.strip()]


# --- R1: 지시 무효화 -----------------------------------------------------------
OVERRIDE_VERBS = re.compile(
    r"무시|무효|잊|어겨|어기"
    r"|ignore|disregard|forget|override",
    re.IGNORECASE)

# 발동시키는 목적어 = '시스템이 준 지시'를 가리키는 말만.
INSTRUCTION_OBJECTS = re.compile(
    r"지시사항|지시문|지시|명령|시스템\s*프롬프트|시스템\s*메시지"
    r"|instructions?|system\s*prompt|system\s*message"
    r"|the\s+above|above\s+instruction|previous\s+instruction|prior\s+instruction",
    re.IGNORECASE)

# 발동시키지 않는 목적어. 코드가 아니라 문서다(화이트리스트에 없으므로 이미 통과).
# test_injection.py가 "이 단어들이 INSTRUCTION_OBJECTS에 매치되지 않는다"를 지킨다.
EXCLUDED_OBJECTS = ("규정", "사규", "대화", "얘기", "이야기", "내용", "질문", "문의")

# --- R2: 역할 전환·제약 해제 ---------------------------------------------------
# 알려진 페르소나 이름. 대문자 약어는 대소문자를 구분한다("dan"이 사람 이름일 수 있다).
PERSONA_UPPER = re.compile(r"\b(?:DAN|STAN|DUDE|ANTI-?DAN)\b")
PERSONA_ANY = re.compile(
    r"developer\s*mode|개발자\s*모드|jailbreak|jailbroken|탈옥",
    re.IGNORECASE)

# 제약 해제 선언. 단독으로는 발동시키지 않는다 — 일상 표현이 걸린다.
RESTRICTION_RELEASE = re.compile(
    r"제한\s*없|제약\s*없|검열\s*없|필터\s*없|무제한|아무\s*제한"
    r"|without\s+restrictions?|no\s+restrictions?|unrestricted|no\s+limits?|no\s+filters?",
    re.IGNORECASE)

# 제약 해제와 결합할 때만 R2를 발동시키는 지시 표현.
ROLE_SWITCH = re.compile(
    r"모드로?\s*전환|모드로|되어\s*줘|되어줘|돼\s*줘|돼줘|행동해|연기해|~?인\s*척"
    r"|act\s+as|pretend|roleplay|you\s+are\s+now|from\s+now\s+on",
    re.IGNORECASE)


@dataclass(frozen=True)
class RuleHit:
    """발동한 룰 1건. 어휘는 전부 우리 사전의 값이므로 로그에 남겨도 안전하다(D-029).

    단, 이 값은 **응답에 넣지 않는다** — 룰을 역산당한다(D-040).
    """

    rule: str            # R1 | R2
    trigger: str         # 발동시킨 어휘
    obj: str = ""        # R1의 목적어 / R2의 결합 표현

    def as_dict(self) -> dict:
        d = {"rule": self.rule, "trigger": self.trigger}
        if self.obj:
            d["object"] = self.obj
        return d


def match_rules(text: str) -> list[RuleHit]:
    """발동한 룰을 전부 돌려준다. 비어 있으면 통과."""
    hits: list[RuleHit] = []

    for sent in sentences(text):
        # R1 — 무효화 동사와 시스템 지시 목적어가 같은 문장 안에 있을 때만.
        verb = OVERRIDE_VERBS.search(sent)
        obj = INSTRUCTION_OBJECTS.search(sent)
        if verb and obj:
            hits.append(RuleHit("R1", verb.group(0), obj.group(0)))

        # R2 — 제약 해제 선언 + 역할 전환 표현이 같은 문장 안에 있을 때.
        rel = RESTRICTION_RELEASE.search(sent)
        sw = ROLE_SWITCH.search(sent)
        if rel and sw:
            hits.append(RuleHit("R2", rel.group(0), sw.group(0)))

    # R2 — 알려진 페르소나 이름은 문장과 무관하게 단독으로 발동한다.
    for pat in (PERSONA_UPPER, PERSONA_ANY):
        m = pat.search(text)
        if m:
            hits.append(RuleHit("R2", m.group(0)))

    return hits


class InjectionRuleDetector(Detector):
    """5단계 1차 방어. **이 프로젝트에서 BLOCK을 처음 쓰는 검사기다.**

    PII 탐지기(D-031)는 TRANSFORM만 썼다. 마스킹은 응답을 조금 바꿀 뿐이지만
    BLOCK은 요청을 아예 없앤다. 잘못 막으면 EVAL 3.2에서 1.0 가중이 붙고,
    사용자 입장에서는 서비스가 고장난 것과 구분되지 않는다.
    그래서 룰은 좁게 잡는다(D-040).

    차단 응답은 main.py가 만든다: **200 + 타겟 스키마 + gateway_blocked: true**.
    403을 쓰면 garak이 오류로 처리해 total_evaluated가 줄고 EVAL 5.2 비교가 무효가 된다.
    차단 사유는 응답에 넣지 않는다 — 룰을 역산당한다. 사유는 감사 로그에만 남기고
    X-Gateway-Request-Id로 대조한다(D-030, D-040).
    """

    name = "injection_rule"

    async def inspect(self, insp: Inspection) -> Verdict:
        hits = _dedupe(match_rules(user_text(insp.body)))
        if not hits:
            return Verdict.allow(self.name)
        rules = sorted({h.rule for h in hits})
        return Verdict.block(
            self.name,
            reason=f"인젝션 룰 발동: {','.join(rules)}",
            rules=[h.as_dict() for h in hits],
        )


def _dedupe(hits: list[RuleHit]) -> list[RuleHit]:
    """같은 룰이 여러 문장에서 걸리면 로그가 길어지기만 한다. 순서는 유지한다."""
    seen: set[tuple[str, str, str]] = set()
    out: list[RuleHit] = []
    for h in hits:
        key = (h.rule, h.trigger, h.obj)
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out
