"""PII 탐지기 — 4-D(탐지) / 4-E(마스킹). mode로 나뉜다.

  mode="detect"  탐지만 한다. 판정은 항상 ALLOW. (검사기 이름 `pii`)
  mode="mask"    찾은 값을 토큰으로 치환한다. 판정은 TRANSFORM. (검사기 이름 `pii_mask`)

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
import re
from dataclasses import dataclass
from datetime import date

from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.vault import TokenVault

# --- 패턴 --------------------------------------------------------------------
# 앞뒤에 숫자나 하이픈이 붙어 있으면 매치하지 않는다.
# 계좌번호 "302-1122-3344-55"의 앞부분만 전화번호로 오인하는 것을 막는 장치.
_NOT_ADJACENT = r"(?<![\d-])"
_NOT_TRAILING = r"(?![\d-])"

RRN_RE = re.compile(_NOT_ADJACENT + r"(\d{2})(\d{2})(\d{2})[-\s]?([1-8])(\d{6})" + _NOT_TRAILING)

# 카드번호: 13~19자리. 구분자는 하이픈/공백만 허용.
CARD_RE = re.compile(_NOT_ADJACENT + r"\d(?:[ -]?\d){12,18}" + _NOT_TRAILING)

# 전화번호: 반드시 0으로 시작하는 한국 접두사만. 이것만으로 계좌번호 오탐이 대부분 걸러진다.
PHONE_RE = re.compile(
    _NOT_ADJACENT + r"(?:01[016789]|02|0[3-6][1-5])[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NOT_TRAILING)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 겹치는 후보가 생겼을 때의 우선순위(작을수록 우선). 주민번호 13자리는 카드 패턴에도 걸린다.
PRIORITY = {"rrn": 0, "card": 1, "phone": 2, "email": 3}

_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_CENTURY = {"1": 1900, "2": 1900, "3": 2000, "4": 2000,
            "5": 1900, "6": 1900, "7": 2000, "8": 2000}


@dataclass(frozen=True)
class Finding:
    """탐지 결과. **원본 값을 담지 않는다**(D-029: 로그에 평문 금지)."""

    kind: str          # rrn | card | phone | email
    start: int
    end: int
    confidence: str    # strong | weak

    def as_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end,
                "len": self.end - self.start, "confidence": self.confidence}


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def rrn_checksum_ok(d: str) -> bool:
    """구 체계 검증번호. 2020-10 이후 발급분은 여기서 False가 나오는 게 정상이다."""
    if len(d) != 13:
        return False
    total = sum(int(a) * w for a, w in zip(d[:12], _RRN_WEIGHTS))
    return (11 - total % 11) % 10 == int(d[12])


def rrn_date_ok(yy: str, mm: str, dd: str, gender: str) -> bool:
    base = _CENTURY.get(gender)
    if base is None:
        return False
    try:
        date(base + int(yy), int(mm), int(dd))
    except ValueError:
        return False
    return True


def luhn_ok(d: str) -> bool:
    total, parity = 0, len(d) % 2
    for i, ch in enumerate(d):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def find_all(text: str) -> list[Finding]:
    """겹치지 않는 탐지 결과를 위치 순으로 돌려준다."""
    cands: list[Finding] = []

    for m in RRN_RE.finditer(text):
        yy, mm, dd, gender, tail = m.groups()
        if not rrn_date_ok(yy, mm, dd, gender):
            continue
        conf = "strong" if rrn_checksum_ok(digits(m.group(0))) else "weak"
        cands.append(Finding("rrn", m.start(), m.end(), conf))

    for m in CARD_RE.finditer(text):
        d = digits(m.group(0))
        if 13 <= len(d) <= 19 and luhn_ok(d):
            cands.append(Finding("card", m.start(), m.end(), "strong"))

    for m in PHONE_RE.finditer(text):
        cands.append(Finding("phone", m.start(), m.end(), "strong"))

    for m in EMAIL_RE.finditer(text):
        cands.append(Finding("email", m.start(), m.end(), "strong"))

    # 겹침 해소: 우선순위 → 긴 것 순으로 자리를 차지한다.
    cands.sort(key=lambda f: (PRIORITY[f.kind], -(f.end - f.start), f.start))
    taken: list[Finding] = []
    for f in cands:
        if any(f.start < t.end and t.start < f.end for t in taken):
            continue
        taken.append(f)
    return sorted(taken, key=lambda f: f.start)


def session_of(body: bytes, fallback: str) -> str:
    """마스킹 매핑을 묶을 키. AnythingLLM의 sessionId를 쓴다(D-013).

    sessionId가 없으면 요청 단위로 격리한다. 남의 세션 토큰이 섞이는 것보다
    복원이 안 되는 쪽이 안전하다.
    """
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return fallback
    if isinstance(obj, dict):
        sid = obj.get("sessionId")
        if isinstance(sid, str) and sid:
            return sid
    return fallback


ALL_KINDS = ("rrn", "card", "phone", "email")


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
        text = insp.body.decode("utf-8", errors="ignore")
        found = [f for f in find_all(text) if f.kind in self.kinds]
        if not found:
            return Verdict.allow(self.name)

        counts: dict[str, int] = {}
        for f in found:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        meta = {"pii": counts, "findings": [f.as_dict() for f in found]}

        if self.mode == "detect":
            return Verdict.allow(self.name, **meta)

        session = session_of(insp.body, insp.request_id)
        # 번호는 앞에서부터 매기고(로그를 읽기 쉽게), 치환은 뒤에서부터 한다(위치값 보존).
        tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end]) for f in found]
        masked = text
        for f, token in zip(reversed(found), reversed(tokens)):
            masked = masked[:f.start] + token + masked[f.end:]

        return Verdict.transform(self.name, masked.encode("utf-8"),
                                 f"PII {len(found)}건 마스킹", masked=len(found), **meta)
