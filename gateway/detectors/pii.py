"""PII 탐지기 — 4-D(탐지) / 4-E(마스킹). mode로 나뉜다.

  mode="detect"  탐지만 한다. 판정은 항상 ALLOW. (검사기 이름 `pii`)
  mode="mask"    찾은 값을 토큰으로 치환한다. 판정은 TRANSFORM. (검사기 이름 `pii_mask`)

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
import re
from dataclasses import dataclass
from datetime import date

from gateway.detectors.base import Detector, Inspection, Verdict
from gateway.openai_api import (CHAT_COMPLETIONS_PATH, PII_ROLES,
                                map_chat_texts, parse_chat_request)
from gateway.vault import TokenVault

# --- 패턴 --------------------------------------------------------------------
# 앞뒤에 숫자·하이픈·ASCII 알파벳이 붙어 있으면 매치하지 않는다. 두 종류의 오탐을 막는다.
#  (1) 계좌번호 "302-1122-3344-55"의 앞부분만 전화번호로 오인
#  (2) 16진 인코딩 문자열 속 숫자 덩어리를 카드번호로 오인
#      예: garak encoding.InjectBase16의 "50726169726965206E6967676572"에는
#      17자리 숫자 연속이 들어 있고 Luhn을 우연히 통과한다. 이걸 마스킹하면
#      공격 프롬프트가 훼손되어 ASR이 가짜로 떨어진다(2026-08-07 실측 17건).
# 한글은 ASCII 알파벳이 아니므로 "4111-1111-1111-1111로 결제"는 그대로 탐지된다.
_NOT_ADJACENT = r"(?<![0-9A-Za-z-])"
_NOT_TRAILING = r"(?![0-9A-Za-z-])"

RRN_RE = re.compile(_NOT_ADJACENT + r"(\d{2})(\d{2})(\d{2})[-\s]?([1-8])(\d{6})" + _NOT_TRAILING)

# 카드번호: 13~19자리. 구분자는 하이픈/공백만 허용.
CARD_RE = re.compile(_NOT_ADJACENT + r"\d(?:[ -]?\d){12,18}" + _NOT_TRAILING)

# 전화번호: 반드시 0으로 시작하는 한국 접두사만. 이것만으로 계좌번호 오탐이 대부분 걸러진다.
PHONE_RE = re.compile(
    _NOT_ADJACENT + r"(?:01[016789]|02|0[3-6][1-5])[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NOT_TRAILING)

# 로컬 파트는 64자까지(RFC 5321 상한). 2026-10-08 이전에는 `+`였는데, `@` 없는 긴 영숫자 줄에서
# 시작 위치마다 끝까지 다시 훑어 입력 길이의 제곱으로 느려졌다 — 40KB 한 줄에 1.9초, 워커 1개라
# 그동안 게이트웨이 전체가 멈춘다(D-099). 64자 안의 주소는 예전과 같은 구간이 잡힌다.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 기밀정보(자격 증명) — 형식이 확실한 것만 잡는다(D-099). 접두사가 고정된 키와 개인 키 블록이다.
# 엔트로피로 "비밀 같은 문자열"을 추측하지 않는다: base64·hex 공격 문자열을 비밀로 오인해 가리면
# 공격 프롬프트가 훼손되어 ASR이 가짜로 떨어진다(위 카드번호 오탐과 같은 함정).
# 개인 키 본문은 `-----END`·큰따옴표를 만나거나 8,192자에서 멈춘다. 역슬래시는 다음 글자와 짝으로 먹는다 —
# 옛 경로의 재직렬화 텍스트에서 `\"`의 역슬래시만 먹고 멈추면 따옴표가 문자열 밖으로 새어 JSON이 깨졌다(D-102). END가 없어도 실패하지 않으므로
# 되짚기가 없다. 암호화 PEM의 `Proc-Type:` 머리줄도 본문으로 함께 가린다. 큰따옴표에서 멈추는 이유:
# 옛 경로는 JSON 본문 전체를 훑으므로, 잘린 키 뒤에서 문자열 밖(JSON 구조)까지 먹으면 본문이 깨진다.
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-[A-Za-z0-9_-]{20,}"                                     # OpenAI·Anthropic API 키
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}"                                # AWS 액세스 키 ID
    r"|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}"  # GitHub 토큰
    r"|AIza[0-9A-Za-z_-]{35}"                                    # Google API 키
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"                             # Slack 토큰
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"   # JWT
    r")(?![A-Za-z0-9_-])"
    r'|-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----(?:[^-"\\]|\\[\s\S]|-(?!----END)){0,8192}'
    r"(?:-----END [A-Z ]{0,40}PRIVATE KEY-----)?")

# 겹치는 후보가 생겼을 때의 우선순위(작을수록 우선). 주민번호 13자리는 카드 패턴에도 걸린다.
# 자격 증명이 맨 앞이다 — 키 안의 숫자 덩어리가 따로 잡혀 키가 조각으로 남으면 안 된다.
PRIORITY = {"secret": 0, "rrn": 1, "card": 2, "phone": 3, "email": 4}

_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_CENTURY = {"1": 1900, "2": 1900, "3": 2000, "4": 2000,
            "5": 1900, "6": 1900, "7": 2000, "8": 2000}


@dataclass(frozen=True)
class Finding:
    """탐지 결과. **원본 값을 담지 않는다**(D-029: 로그에 평문 금지)."""

    kind: str          # rrn | card | phone | email | secret
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
    """겹치지 않는 탐지 결과를 위치 순으로 돌려준다.

    종류마다 우선순위가 다르고(PRIORITY), 한 종류의 매치는 finditer가 왼쪽부터 겹치지 않게 내놓는다.
    그래서 우선순위 순으로 종류를 돌며 이미 자리 잡은 구간(위치 순)과 두 포인터로 한 번만 비교한다 —
    탐지 건수에 선형이다. 결과는 예전 방식(후보 전체를 우선순위·길이·위치로 정렬해 탐욕적으로 고르기)과 같다.
    2026-10-29 이전에는 후보마다 자리 잡은 구간 전체를 훑어 건수의 제곱으로 느려졌다 — 전화번호 2만 개(273KB)에
    4초, 1MiB에 60초. 워커 1개라 그동안 게이트웨이 전체가 멈춘다(D-102).
    """
    by_kind: dict[str, list[Finding]] = {k: [] for k in PRIORITY}

    for m in SECRET_RE.finditer(text):
        by_kind["secret"].append(Finding("secret", m.start(), m.end(), "strong"))

    for m in RRN_RE.finditer(text):
        yy, mm, dd, gender, tail = m.groups()
        if not rrn_date_ok(yy, mm, dd, gender):
            continue
        conf = "strong" if rrn_checksum_ok(digits(m.group(0))) else "weak"
        by_kind["rrn"].append(Finding("rrn", m.start(), m.end(), conf))

    for m in CARD_RE.finditer(text):
        d = digits(m.group(0))
        if 13 <= len(d) <= 19 and luhn_ok(d):
            by_kind["card"].append(Finding("card", m.start(), m.end(), "strong"))

    for m in PHONE_RE.finditer(text):
        by_kind["phone"].append(Finding("phone", m.start(), m.end(), "strong"))

    for m in EMAIL_RE.finditer(text):
        by_kind["email"].append(Finding("email", m.start(), m.end(), "strong"))

    taken: list[Finding] = []
    for kind in sorted(PRIORITY, key=PRIORITY.__getitem__):
        taken = _merge_free(taken, by_kind[kind])
    return taken


def _merge_free(taken: list[Finding], cands: list[Finding]) -> list[Finding]:
    """taken(위치 순, 서로 겹치지 않음)에 cands(위치 순, 서로 겹치지 않음) 중 taken과 겹치지 않는 것만
    더해 위치 순으로 돌려준다. 두 목록을 각각 한 번씩만 지난다."""
    out: list[Finding] = []
    i = 0
    for c in cands:
        while i < len(taken) and taken[i].end <= c.start:
            out.append(taken[i])
            i += 1
        if i < len(taken) and taken[i].start < c.end:
            continue          # 더 높은 우선순위가 이미 차지한 자리
        out.append(c)
    out.extend(taken[i:])
    return out


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
        if insp.path == CHAT_COMPLETIONS_PATH:
            return self._inspect_chat(insp)

        text = normalized_text(insp.body)   # L-005: \uXXXX를 먼저 되돌린다
        found = [f for f in find_all(text) if f.kind in self.kinds]
        found = _outside(found, _session_spans(text, insp.body))   # 세션 키는 가리지 않는다(D-102)
        if not found:
            return Verdict.allow(self.name)
        meta = _meta(found)

        if self.mode == "detect":
            return Verdict.allow(self.name, **meta)

        session = insp.session or session_of(insp.body, insp.request_id)
        tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end]) for f in found]
        masked = _replace(text, found, tokens)

        return Verdict.transform(self.name, masked.encode("utf-8"),
                                 f"PII {len(found)}건 마스킹", masked=len(found), **meta)

    def _inspect_chat(self, insp: Inspection) -> Verdict:
        payload = parse_chat_request(insp.body)
        session = insp.session or session_of(insp.body, insp.request_id)
        found: list[Finding] = []

        def inspect_text(text: str) -> str:
            local = [f for f in find_all(text) if f.kind in self.kinds]
            found.extend(local)
            if self.mode == "detect":
                return text
            tokens = [self.vault.token_for(session, f.kind, text[f.start:f.end]) for f in local]
            return _replace(text, local, tokens)

        map_chat_texts(payload, PII_ROLES, inspect_text)
        if not found:
            return Verdict.allow(self.name)
        meta = _meta(found)
        if self.mode == "detect":
            return Verdict.allow(self.name, **meta)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return Verdict.transform(self.name, body, f"PII {len(found)}건 마스킹",
                                 masked=len(found), **meta)

    async def on_response(self, session: str, text: str) -> tuple[str, dict] | None:
        """응답에 남은 토큰을 원본으로 되돌린다(4-F).

        사용자는 자기가 보낸 값을 그대로 돌려받아야 한다. 토큰이 그대로 노출되면
        EVAL 3.2의 '부분 저하'로 집계되어 FPR을 밀어올린다.
        """
        if self.mode != "mask":
            return None
        restored, n = self.vault.restore(session, text, _json_escape if _is_json(text) else None)
        residual = self.vault.residual_tokens(restored)
        if n == 0 and residual == 0:
            return None
        # residual > 0 이면 복원에 실패한 토큰이 사용자에게 나간다는 뜻이다.
        # 조용히 넘기지 않고 로그에 남겨 측정 때 잡히게 한다.
        return restored, {"restored": n, "residual_tokens": residual}

    async def release(self, session: str) -> None:
        """다시 쓰일 일이 없는 세션의 원문을 지운다(D-099). TTL까지 기다리지 않는다."""
        self.vault.drop(session)
