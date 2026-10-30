"""PII 탐지기 — 4-D(탐지) / 4-E(마스킹). mode로 나뉜다.

  mode="detect"  탐지만 한다. 판정은 항상 ALLOW. (검사기 이름 `pii`)
  mode="mask"    찾은 값을 같은 모양의 대체값으로 치환한다(D-107 B, surrogate.py). 판정은 TRANSFORM. (검사기 이름 `pii_mask`)

탐지 대상은 정형 식별자 4종(주민번호·카드·전화·이메일)과 형식이 확실한 자격 증명(`secret`,
D-099)이다. 자격 증명도 같은 볼트·같은 토큰 형식으로 가리고 응답에서 되돌린다 — 사용자가
붙여 넣은 키는 외부 AI로 나가지 않고, 사용자 자신에게는 그대로 돌아온다.

차단(BLOCK)은 쓰지 않는다. SCOPE 2절의 위협은 "외부 API 로그에 민감정보 잔존"이고
마스킹으로 이미 해소된다. 또 FPR 5% 예산은 5단계 인젝션 탐지기와 나눠 써야 한다.
정상 질문셋 13문항이 PII를 담고 있어, 차단을 택하면 그것만으로 FPR 13%가 된다.

왜 탐지와 조치를 나누는가:
  마스킹/차단 정책을 먼저 정하면 "얼마나 잘 잡는지"를 모르는 채로 정하게 된다.
  먼저 탐지 성능을 정상 질문셋(EVAL 3.1, 100문항)에 대고 재고, 그 숫자를 보고
  4-E에서 정책을 정한다. 순서를 지키면 정책 결정에 근거가 생긴다.

주민등록번호 체크섬을 '필수 조건'이 아니라 '신뢰도 등급'으로만 쓰는 이유:
  (1) 2020년 10월 주민등록번호 부여체계 개편으로 뒷자리가 임의번호가 되면서,
      그 이후 발급분은 기존 검증식을 통과하지 못한다.
  (2) 우리 정상 질문셋의 합성 주민번호 3개(P-111~113)도 전부 체크섬 불일치다.
  체크섬을 필수로 걸면 이들을 전부 놓친다. 탐지 실패 = 유출이므로 잡고 등급을 남긴다.
"""
from __future__ import annotations

import json

from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.openai_api import PII_ROLES
from gateway.vault import TokenVault

# 탐지 패턴·검증식·겹침 해소는 patterns.py에 있다(D-107 B). 이름은 여기서도 그대로 쓴다(테스트·변이 검사 호환).
from gateway.detectors.patterns import (  # noqa: E402,F401
    CARD_RE, EMAIL_RE, INTL_PHONE_RE, PAREN_PHONE_RE, PHONE_RE, PRIORITY, RRN_RE, SECRET_RE,
    Finding, digits, find_all, luhn_ok, rrn_checksum_ok, rrn_date_ok)


def _replace(text: str, found: list[Finding], tokens: list[str]) -> str:
    """found(위치 순)의 구간을 tokens로 바꾼 텍스트. 조각을 모아 한 번에 잇는다 —
    건마다 문자열 전체를 다시 복사하면 길이×건수로 느려진다(D-102)."""
    out: list[str] = []
    pos = 0
    for f, token in zip(found, tokens):
        out.append(text[pos:f.start])
        out.append(token)
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


# 감사 로그에 남기는 탐지 위치 목록의 상한. 건수는 `pii`에 종류별로 다 남고, 위치는 앞 100건만 남긴다 —
# 전화번호 7만 개짜리 요청 하나가 감사 한 줄을 6MB로 만들었다(D-102).
FINDINGS_LIMIT = 100


def _meta(found: list[Finding]) -> dict:
    counts: dict[str, int] = {}
    for f in found:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    meta = {"pii": counts, "findings": [f.as_dict() for f in found[:FINDINGS_LIMIT]]}
    if len(found) > FINDINGS_LIMIT:
        meta["findings_omitted"] = len(found) - FINDINGS_LIMIT
    return meta


def _session_spans(text: str, body: bytes) -> list[tuple[int, int]]:
    """재직렬화한 옛 경로 본문에서 `sessionId` 값이 차지하는 구간들.

    세션 키는 상류(AnythingLLM)가 대화를 나누는 열쇠다. 값이 개인정보 모양이라고 가리면 토큰 번호에 따라
    키가 바뀌어 같은 대화가 갈라지고, 쿼리로 오는 조회(`?sessionId=`)와도 어긋난다(D-102).
    그 값은 게이트웨이가 보호할 입력이 아니라 주소다 — 그대로 둔다.
    """
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return []
    sid = obj.get("sessionId") if isinstance(obj, dict) else None
    if not isinstance(sid, str) or not sid:
        return []
    needle = json.dumps({"sessionId": sid}, ensure_ascii=False)[1:-1]   # "sessionId": "…"
    head = len(json.dumps({"sessionId": ""}, ensure_ascii=False)[1:-2])  # 값 앞까지의 길이
    spans, i = [], text.find(needle)
    while i != -1:
        spans.append((i + head, i + len(needle) - 1))
        i = text.find(needle, i + 1)
    return spans


def _outside(found: list[Finding], spans: list[tuple[int, int]]) -> list[Finding]:
    return [f for f in found if not any(f.start < e and s < f.end for s, e in spans)]


def normalized_text(body: bytes) -> str:
    r"""정규식을 돌릴 본문 텍스트. **원문 바이트를 그대로 쓰지 않는다** (L-005 / D-055).

    JSON은 한글을 두 가지로 담는다.
        ensure_ascii=False → {"message": "번호900101-1234563"}
        ensure_ascii=True  → {"message": "\ubc88\ud638900101-1234563"}

    두 번째에서 주민번호 앞 문자가 한글 `호`가 아니라 이스케이프의 `8`이 되고,
    숫자 패턴의 경계 조건 `(?<![0-9A-Za-z-])`에 걸려 **조용히 미탐**이 난다.
    로그에는 `allow`만 남아서 정상처럼 보인다 — 이 프로젝트가 가장 경계하는 실패다.

    `json.loads`가 `\uXXXX`를 실제 문자로 되돌려주므로, 파싱한 뒤 `ensure_ascii=False`로
    다시 직렬화해 넘긴다. 5-A의 `injection.py`가 `user_text()`로 한 것과 같은 처방이다.

    **입력 필드만 꺼내지 않고 본문 전체를 재직렬화하는 이유**: 마스킹은 본문을 통째로
    치환해 돌려줘야 하는데, 필드만 꺼내면 나머지를 다시 조립해야 하고 그 조립 과정이
    새 버그 자리가 된다. 재직렬화는 의미를 보존하면서 이스케이프만 푼다.

    파싱에 실패하면 예전처럼 통째로 디코딩한다. 놓치는 것보다는 낫다.
    """
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body.decode("utf-8", errors="ignore")
    return json.dumps(obj, ensure_ascii=False)


def _is_json(text: str) -> bool:
    """응답 본문이 JSON인가. JSON이면 토큰은 문자열 리터럴 안에만 있을 수 있다
    (`PII:kind:n`은 문자열 밖에서 JSON 문법이 아니다)."""
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _json_escape(value: str) -> str:
    r"""JSON 문자열 리터럴 안에 넣을 형태. 원본에 줄바꿈·탭이 있으면(전화번호 구분자 \s)
    날것으로 끼울 때 응답 JSON이 깨졌다 — 2026-10-01 리뷰 결함."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


ALL_KINDS = ("rrn", "card", "phone", "email", "secret")


class PIIDetector(Detector):
    def __init__(self, mode: str = "detect", kinds: tuple[str, ...] = ALL_KINDS,
                 vault: TokenVault | None = None) -> None:
        if mode not in ("detect", "mask"):
            raise ValueError(f"mode는 detect 또는 mask여야 한다: {mode!r}")
        self.mode = mode
        self.kinds = kinds
        self.name = "pii" if mode == "detect" else "pii_mask"
        self.vault = vault or TokenVault()

    async def inspect(self, insp: Inspection) -> Verdict:
        if insp.doc is not None:
            return self._inspect_doc(insp)

        text = normalized_text(insp.body)   # L-005: \uXXXX를 먼저 되돌린다
        found = [f for f in find_all(text) if f.kind in self.kinds]
        found = _outside(found, _session_spans(text, insp.body))   # 세션 키는 가리지 않는다(D-102)
        if not found:
            return Verdict.allow(self.name)
        meta = _meta(found)

        if self.mode == "detect":
            return Verdict.allow(self.name, **meta)

        session = insp.session or insp.request_id   # 볼트는 요청 단위다(D-107 A)
        tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end]) for f in found]
        masked = _replace(text, found, tokens)

        return Verdict.transform(self.name, masked.encode("utf-8"),
                                 f"PII {len(found)}건 마스킹", masked=len(found), **meta)

    def _inspect_doc(self, insp: Inspection) -> Verdict:
        """어댑터 경로(D-107 C): user·assistant 텍스트(도구 호출 인자 포함)만 제자리에서 가린다. 직렬화는 체인이 한다."""
        doc, session = insp.doc, insp.session or insp.request_id
        found: list[Finding] = []
        for ref in doc.texts():
            if ref.role not in PII_ROLES:
                continue
            text = ref.get()
            local = [f for f in find_all(text) if f.kind in self.kinds]
            if not local:
                continue
            found.extend(local)
            if self.mode == "mask":
                tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end]) for f in local]
                doc.put(ref, _replace(text, local, tokens))
        if not found:
            return Verdict.allow(self.name)
        meta = _meta(found)
        if self.mode == "detect":
            return Verdict.allow(self.name, **meta)
        return Verdict.transform(self.name, doc.serialize(), f"PII {len(found)}건 마스킹", masked=len(found), **meta)

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답에 남은 토큰을 원본으로 되돌린다(4-F).

        사용자는 자기가 보낸 값을 그대로 돌려받아야 한다. 토큰이 그대로 노출되면
        EVAL 3.2의 '부분 저하'로 집계되어 FPR을 밀어올린다.
        """
        if self.mode != "mask" or not self.vault.issued(session):
            return None
        restored, n = self.vault.restore(session, text, _json_escape if _is_json(text) else None)
        residual = self.vault.residual(session, restored)
        # residual > 0 이면 복원에 실패한 대체값이 사용자에게 가짜 값으로 나간다는 뜻이다(D-107 B — 토큰과 달리 눈에 안 띈다).
        # 조용히 넘기지 않고 로그에 남겨 운영·측정 때 잡히게 한다. 발급 수(issued)와 함께 비율을 본다.
        return restored, {"restored": n, "residual_tokens": residual, "issued": self.vault.issued(session)}

    async def release(self, session: str) -> None:
        """다시 쓰일 일이 없는 세션의 원문을 지운다(D-099). TTL까지 기다리지 않는다."""
        self.vault.drop(session)
