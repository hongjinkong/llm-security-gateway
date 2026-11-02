"""PII 탐지기 — 4-D(탐지) / 4-E(마스킹). mode로 나뉜다.

  mode="detect"  탐지만 한다. 판정은 항상 ALLOW. (검사기 이름 `pii`)
  mode="mask"    찾은 값을 같은 모양의 대체값으로 치환한다(D-107 B, surrogate.py). 판정은 TRANSFORM. (검사기 이름 `pii_mask`)

탐지 대상은 정형 식별자(주민번호·카드·전화·이메일, D-117에서 외국인등록번호·여권·운전면허·사업자·법인·계좌·IPv4)와
형식이 확실한 자격 증명(`secret`, D-099)이다. 자격 증명도 같은 볼트·같은 대체값으로 가리고 응답에서 되돌린다 — 사용자가
붙여 넣은 키는 외부 AI로 나가지 않고, 사용자 자신에게는 그대로 돌아온다. 사업자·법인·계좌·IPv4는 기본으로 감사에만 남긴다(D-117).
D-126: 이름·주소·직장(`person`·`address`·`org`)은 탐지 사이드카(detect/, 한국어 NER)가 찾는다 — 정책이 `pii_kinds`에 넣어야 켜지고(기본 꺼짐),
`GATEWAY_DETECT_URL`이 필요하다. 정규식 탐지 뒤 사이드카 구간을 더하되 겹치면 정규식이 우선, 주소는 숫자가 든 토큰이 있을 때만 가리고, `org`는 기본 감사만.
사이드카가 실패하면 가리는 NER 종류가 있는 mask 정책은 `GATEWAY_DETECT_FAIL`대로 503(closed) 또는 정규식 종류만 가리고 통과(open), 그 밖은 늘 통과(`ner_error`).

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
import dataclasses
import json
import time
from typing import Any

from gateway.api.base import ApiError
from gateway.detect_client import DetectClient, DetectUnavailable, Span
from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.openai_api import PII_ROLES
from gateway.vault import TokenVault, map_strings, norm_key, strings

# 탐지 패턴·검증식·겹침 해소는 patterns.py에 있다(D-107 B). 이름은 여기서도 그대로 쓴다(테스트·변이 검사 호환).
from gateway.detectors.patterns import (  # noqa: E402,F401
    CARD_RE, EMAIL_RE, INTL_PHONE_RE, NER_KINDS, PAREN_PHONE_RE, PHONE_RE, PRIORITY, RRN_RE, SECRET_RE,
    Finding, _disjoint, _merge_free, card_brand_ok, digits, find_all, luhn_ok, normalize, rrn_checksum_ok, rrn_date_ok)


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


def _counts(found: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in found:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return counts


def _meta(found: list[Finding], masking: bool) -> dict:
    """mask 모드의 `pii`는 가린 것만 센다(지표 gateway_pii_masked_total). 가리지 않은 탐지(D-116)는 `unmasked`에 따로."""
    meta: dict[str, Any] = {"pii": _counts([f for f in found if f.mask or not masking]),
            "findings": [f.as_dict() for f in found[:FINDINGS_LIMIT]]}
    left = [f for f in found if not f.mask]
    if masking and left:
        meta["unmasked"] = _counts(left)
    if len(found) > FINDINGS_LIMIT:
        meta["findings_omitted"] = len(found) - FINDINGS_LIMIT
    return meta


REGEX_KINDS = ("rrn", "frn", "passport", "driver", "card", "phone", "email", "secret", "brn", "crn", "account", "ipv4")
# 설정이 받는 전체 종류 = 정규식 12 + 사이드카 NER 3(D-126). 기본 GATEWAY_PII_KINDS는 REGEX_KINDS다 — 이름·주소·직장은 정책이 켠다(기본 꺼짐)
ALL_KINDS = REGEX_KINDS + NER_KINDS
# 탐지해 감사에만 남기고 가리지 않는 종류의 기본값(D-117, GATEWAY_PII_DETECT_KINDS) — 계좌는 꼴이 은행마다 다르고 검증식이 없다,
# 사업자·법인 번호는 공개 의무가 있는 사업체 식별자, IPv4는 개발 대화의 서버 주소가 대부분이라 가리면 질문의 뜻이 바뀐다.
# 직장(org, D-126)도 — 회사 이름을 가짜로 바꾸면 '삼성전자 주가' 같은 질문의 답이 망가진다.
DETECT_ONLY = ("account", "brn", "crn", "ipv4", "org")
FAIL_MODES = ("closed", "open")        # GATEWAY_DETECT_FAIL — 사이드카 실패 때 가리는 NER 종류가 있는 mask 정책의 동작(D-126)
# 이보다 긴 검사 텍스트의 정규식 탐지는 스레드에서 돈다 — 이벤트 루프가 다른 요청을 계속 받는다(D-110). 볼트 조작은 루프에 둔다.
OFFLOAD_CHARS = 16 * 1024
# `avoid`(대체값이 요청에 이미 있는 글자열인지)는 새 NER 대체값 수 × 텍스트 길이다 — 이보다 긴 요청은 보지 않는다(D-126 리뷰). ponytail: 상한 밖에서는 놓친 실제 이름과의 충돌을 막지 않는다
AVOID_CHARS = 64 * 1024


class PIIDetector(Detector):
    def __init__(self, mode: str = "detect", kinds: tuple[str, ...] = REGEX_KINDS,
                 vault: TokenVault | None = None, max_findings: int = 5000,
                 roles: frozenset[str] = PII_ROLES, detect_kinds: tuple[str, ...] = DETECT_ONLY,
                 detect: DetectClient | None = None, detect_fail: str = "closed") -> None:
        if mode not in ("detect", "mask"):
            raise ValueError(f"mode는 detect 또는 mask여야 한다: {mode!r}")
        if detect_fail not in FAIL_MODES:
            raise ValueError(f"detect_fail은 closed 또는 open이어야 한다: {detect_fail!r}")
        self.mode = mode
        self.kinds = kinds
        self.name = "pii" if mode == "detect" else "pii_mask"
        self.vault = vault or TokenVault()
        self.max_findings = max_findings     # mask 모드에서 한 요청의 탐지 상한(D-110, GATEWAY_MAX_FINDINGS)
        self.roles = roles                   # 가리는 역할(D-112, GATEWAY_PII_ROLES)
        self.detect_kinds = frozenset(detect_kinds)   # 가리지 않고 감사에만 남기는 종류(D-117)
        self.ner_kinds = frozenset(kinds) & frozenset(NER_KINDS)   # 사이드카가 찾는 종류(D-126) — 비면 사이드카를 부르지 않는다
        self.detect = detect if self.ner_kinds else None
        self.detect_fail = detect_fail

    async def prepare(self) -> None:
        if self.detect is not None:
            await self.detect.prepare()

    async def aclose(self) -> None:
        if self.detect is not None:
            await self.detect.aclose()

    async def inspect(self, insp: Inspection) -> Verdict:
        """어댑터가 준 텍스트(D-107 C) 중 user·assistant 텍스트(도구 호출 인자 포함)만 제자리에서 가린다. 직렬화는 체인이 한다.
        어댑터가 파싱한 문자열을 보므로 JSON의 `\\uXXXX` 이스케이프가 정규식을 피해 가지 못한다(L-005)."""
        doc, session = insp.doc, insp.session or insp.request_id
        refs = [r for r in doc.texts() if r.role in self.roles]
        texts = [r.get() for r in refs]

        def scan() -> list[list[Finding]]:
            return [[dataclasses.replace(f, mask=False) if f.kind in self.detect_kinds else f
                     for f in find_all(t) if f.kind in self.kinds] for t in texts]

        per_ref = await asyncio.to_thread(scan) if sum(map(len, texts)) > OFFLOAD_CHARS else scan()
        extra: dict[str, Any] = {}
        if self.detect is not None and texts:
            per_ref = await self._with_ner(per_ref, texts, extra)
        found = [f for local in per_ref for f in local]
        if not found:
            return Verdict.allow(self.name, **extra)
        meta = {**_meta(found, self.mode == "mask"), **extra}
        masking = sum(f.mask for f in found)       # 가리지 않는 탐지(문맥 없는 약한 주민번호·범위 밖 카드 꼴)는 감사에만(D-116)
        if self.mode == "detect" or not masking:
            return Verdict.allow(self.name, **meta)
        if masking > self.max_findings:
            # 대체값을 하나도 발급하기 전에 거절한다 — 가리지 못한 값을 내보내지 않는다(D-110). 413은 main이 그 API의 오류 형식으로 낸다.
            raise ApiError(f"too many sensitive values in request ({masking} > {self.max_findings})",
                           None, "too_many_findings", 413)
        # 이름·주소 대체값이 요청에 이미 있는 글자열이면(대소문자 무관) 다시 만든다(D-126) — 긴 요청은 보지 않는다(AVOID_CHARS)
        avoid = "\n".join(texts).lower() if any(f.kind in self.ner_kinds for f in found) and sum(map(len, texts)) <= AVOID_CHARS else ""
        for ref, text, local in zip(refs, texts, per_ref):
            local = [f for f in local if f.mask]
            if local:
                tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end], avoid) for f in local]
                doc.put(ref, _replace(text, local, tokens))
        return Verdict.transform(self.name, doc.serialize(), f"PII {masking}건 마스킹", masked=masking, **meta)

    async def _with_ner(self, per_ref: list[list[Finding]], texts: list[str], extra: dict[str, Any]) -> list[list[Finding]]:
        """사이드카의 이름·주소·직장 구간을 정규식 탐지에 더한다(D-126). 감사 메타 `ner_ms`(사이드카에 쓴 시간 — 캐시만이면 0에 가깝다)·`ner_error`(실패 사유).
        실패하면: 가리는 NER 종류가 있는 mask 정책은 GATEWAY_DETECT_FAIL대로 503(closed — 상류에 보내지 않는다)이거나 정규식 종류만 가리고 통과(open),
        detect 정책이나 켠 NER 종류가 모두 감사만이면 늘 통과한다."""
        assert self.detect is not None
        t0 = time.perf_counter()
        try:
            spans: list[list[Span]] | None = await self.detect.spans(texts)
        except DetectUnavailable as exc:
            spans, extra["ner_error"] = None, exc.reason
        extra["ner_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        if spans is None:
            if self.mode == "mask" and self.detect_fail == "closed" and self.ner_kinds - self.detect_kinds:
                # 사유(ner_error)·시간은 감사 줄의 검사기 항목으로 남는다 — relay가 meta로 한 단계짜리 체인 결과를 만든다(D-126 리뷰)
                raise ApiError("name/address detection is unavailable", None, "detect_unavailable", 503, "overloaded_error",
                               meta={"detector": self.name, **extra})
            return per_ref
        return [_merge_free(local, self._ner_findings(found, text)) for local, found, text in zip(per_ref, spans, texts)]

    def _ner_findings(self, spans: list[Span], text: str) -> list[Finding]:
        """사이드카 구간 → 탐지 결과. 정규식 탐지와 겹치는 것은 호출자(_merge_free)가 버린다 — 형식 식별자는 정규식이 정확하다."""
        out: list[Finding] = []
        for s in spans:
            if s.kind not in self.ner_kinds or not normalize(text[s.start:s.end]).text.strip():   # 공백·서식 문자뿐인 구간은 가릴 것이 없다
                continue
            # 주소는 숫자가 든 토큰(번지·건물 번호·동·호·층)이 있을 때만 가린다 — 시·도·구·역·나라 이름만이면 감사만('서울 날씨'를 가리면 질문이 바뀐다)
            mask = s.kind not in self.detect_kinds and (s.kind != "address" or any(c.isdigit() for c in text[s.start:s.end]))
            out.append(Finding(s.kind, s.start, s.end, "strong" if s.score >= 0.9 else "weak", mask))
        return _disjoint(out)

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답에 남은 토큰을 원본으로 되돌린다(4-F).

        사용자는 자기가 보낸 값을 그대로 돌려받아야 한다. 토큰이 그대로 노출되면
        EVAL 3.2의 '부분 저하'로 집계되어 FPR을 밀어올린다.
        """
        issued = self.mode == "mask" and self.vault.issued(session)
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if not isinstance(obj, (dict, list)):          # JSON이 아니면 텍스트 전체를 복원한다
            restored, n = self.vault.restore(session, text) if issued else (text, 0)
            visible = restored
        else:
            # 문자열 값마다 복원하고 한 번 직렬화한다. 도구 인자는 안쪽 JSON 이스케이프로(D-113), thinking·reasoning은 건너뛴다(D-112).
            n = map_strings(obj, lambda value, escape: self.vault.restore(session, value, escape)) if issued else 0
            restored = json.dumps(obj, ensure_ascii=False) if n else text
            visible = "\n".join(strings(obj))             # 잔여·의심·새 PII는 사용자에게 복원된 채로 보이는 텍스트에서만 센다
        stats = self.response_stats(session, visible)
        if not issued:                                  # 가린 것이 없으면 출력 방향 관측만(D-120)
            return (text, {"new": stats["new"]}) if stats["new"] else None
        # residual > 0 이면 복원에 실패한 대체값이 사용자에게 가짜 값으로 나간다는 뜻이다(D-107 B — 토큰과 달리 눈에 안 띈다).
        # 조용히 넘기지 않고 로그에 남겨 운영·측정 때 잡히게 한다. 발급 수(issued)와 함께 비율을 본다.
        return restored, {"restored": n, "issued": self.vault.issued(session), **stats}

    def response_stats(self, session: str, visible: str) -> dict[str, int]:
        """사용자에게 보이는 응답 텍스트의 잔여 대체값·의심 잔여(D-113)와 새 PII(D-120) — 탐지 한 번으로.
        새 PII = 이 정책이 가리는 종류의 가리는 탐지 중, 이 요청에서 가린 원문·발급한 대체값이 아닌 것."""
        found = find_all(visible)
        ours = self.vault.known(session)
        new = sum(1 for f in found if f.mask and f.kind in self.kinds and f.kind not in self.detect_kinds
                  and norm_key(f.kind, visible[f.start:f.end]) not in ours)
        residual, suspect = self.vault.leftovers(session, visible, found)      # 한 번만 훑는다(D-126 리뷰)
        return {"residual_tokens": residual, "suspect": suspect, "new": new}

    async def release(self, session: str) -> None:
        """다시 쓰일 일이 없는 세션의 원문을 지운다(D-099). TTL까지 기다리지 않는다."""
        self.vault.drop(session)
