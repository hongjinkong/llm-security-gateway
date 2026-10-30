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

import asyncio
import json

from gateway.api.base import ApiError
from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.openai_api import PII_ROLES
from gateway.vault import TokenVault, map_strings, strings

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


ALL_KINDS = ("rrn", "card", "phone", "email", "secret")
# 이보다 긴 검사 텍스트의 정규식 탐지는 스레드에서 돈다 — 이벤트 루프가 다른 요청을 계속 받는다(D-110). 볼트 조작은 루프에 둔다.
OFFLOAD_CHARS = 16 * 1024


class PIIDetector(Detector):
    def __init__(self, mode: str = "detect", kinds: tuple[str, ...] = ALL_KINDS,
                 vault: TokenVault | None = None, max_findings: int = 5000,
                 roles: frozenset[str] = PII_ROLES) -> None:
        if mode not in ("detect", "mask"):
            raise ValueError(f"mode는 detect 또는 mask여야 한다: {mode!r}")
        self.mode = mode
        self.kinds = kinds
        self.name = "pii" if mode == "detect" else "pii_mask"
        self.vault = vault or TokenVault()
        self.max_findings = max_findings     # mask 모드에서 한 요청의 탐지 상한(D-110, GATEWAY_MAX_FINDINGS)
        self.roles = roles                   # 가리는 역할(D-112, GATEWAY_PII_ROLES)

    async def inspect(self, insp: Inspection) -> Verdict:
        """어댑터가 준 텍스트(D-107 C) 중 user·assistant 텍스트(도구 호출 인자 포함)만 제자리에서 가린다. 직렬화는 체인이 한다.
        어댑터가 파싱한 문자열을 보므로 JSON의 `\\uXXXX` 이스케이프가 정규식을 피해 가지 못한다(L-005)."""
        doc, session = insp.doc, insp.session or insp.request_id
        refs = [r for r in doc.texts() if r.role in self.roles]
        texts = [r.get() for r in refs]

        def scan() -> list[list[Finding]]:
            return [[f for f in find_all(t) if f.kind in self.kinds] for t in texts]

        per_ref = await asyncio.to_thread(scan) if sum(map(len, texts)) > OFFLOAD_CHARS else scan()
        found = [f for local in per_ref for f in local]
        if not found:
            return Verdict.allow(self.name)
        meta = _meta(found)
        if self.mode == "detect":
            return Verdict.allow(self.name, **meta)
        if len(found) > self.max_findings:
            # 대체값을 하나도 발급하기 전에 거절한다 — 가리지 못한 값을 내보내지 않는다(D-110). 413은 main이 그 API의 오류 형식으로 낸다.
            raise ApiError(f"too many sensitive values in request ({len(found)} > {self.max_findings})",
                           None, "too_many_findings", 413)
        for ref, text, local in zip(refs, texts, per_ref):
            if local:
                tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end]) for f in local]
                doc.put(ref, _replace(text, local, tokens))
        return Verdict.transform(self.name, doc.serialize(), f"PII {len(found)}건 마스킹", masked=len(found), **meta)

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답에 남은 토큰을 원본으로 되돌린다(4-F).

        사용자는 자기가 보낸 값을 그대로 돌려받아야 한다. 토큰이 그대로 노출되면
        EVAL 3.2의 '부분 저하'로 집계되어 FPR을 밀어올린다.
        """
        if self.mode != "mask" or not self.vault.issued(session):
            return None
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if not isinstance(obj, (dict, list)):          # JSON이 아니면 텍스트 전체를 복원한다
            restored, n = self.vault.restore(session, text)
            visible = restored
        else:
            # 문자열 값마다 복원하고 한 번 직렬화한다. 도구 인자는 안쪽 JSON 이스케이프로(D-113), thinking·reasoning은 건너뛴다(D-112).
            n = map_strings(obj, lambda value, escape: self.vault.restore(session, value, escape))
            restored = json.dumps(obj, ensure_ascii=False) if n else text
            visible = "\n".join(strings(obj))             # 잔여·의심은 사용자에게 복원된 채로 보이는 텍스트에서만 센다
        residual = self.vault.residual(session, visible)
        # residual > 0 이면 복원에 실패한 대체값이 사용자에게 가짜 값으로 나간다는 뜻이다(D-107 B — 토큰과 달리 눈에 안 띈다).
        # 조용히 넘기지 않고 로그에 남겨 운영·측정 때 잡히게 한다. 발급 수(issued)와 함께 비율을 본다.
        return restored, {"restored": n, "residual_tokens": residual, "issued": self.vault.issued(session),
                          "suspect": self.vault.suspect(session, visible)}

    async def release(self, session: str) -> None:
        """다시 쓰일 일이 없는 세션의 원문을 지운다(D-099). TTL까지 기다리지 않는다."""
        self.vault.drop(session)
