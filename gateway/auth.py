"""클라이언트 인증과 상류 키 보관(D-107 A).

키 모델: 클라이언트는 **게이트웨이 키**를 들고, 공급자(상류) 키는 게이트웨이 환경변수 하나에만 있다.
  GATEWAY_CLIENT_KEYS="이름=키,이름2=키2"   이름을 빼면 키 지문(sha256) 앞 8자리가 이름이다. 없으면 기동 실패 — 닫힌 채로 시작한다.
  GATEWAY_AUTH=off                       로컬 실험용으로만 무인증을 연다(명시해야 한다).
  GATEWAY_UPSTREAM_KEY=…                 있으면 클라이언트의 인증 헤더를 떼고 상류 형식으로 단다. 없으면 클라이언트 헤더를 그대로 넘긴다.

클라이언트는 `Authorization: Bearer <키>`(OpenAI SDK)나 `x-api-key: <키>`(Anthropic SDK)로 낸다. 상류에는 경로에 따라
`/v1/messages*`면 `x-api-key`, 그 밖에는 `Authorization: Bearer`로 단다(Anthropic의 OpenAI 호환 입구도 Bearer를 받는다, D-103).

해시를 저장하지 않고 평문을 비교하는 이유: 상류 키도 같은 환경변수에 평문으로 있으므로 위협 모델이 같다. 비교는 `hmac.compare_digest`.
키 생성: `python -m gateway keygen`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable, Mapping

AUTH_HEADERS = frozenset({"authorization", "x-api-key"})


def keygen() -> str:
    return "gw-" + secrets.token_urlsafe(24)


def parse_client_keys(spec: str) -> dict[str, str]:
    """`이름=키,키2` → {키: 이름}. 이름이 없으면 지문 앞 8자리."""
    out: dict[str, str] = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, key = item.partition("=")
        if not sep:
            name, key = "", item
        key, name = key.strip(), name.strip()
        if not key:
            raise ValueError("GATEWAY_CLIENT_KEYS: 빈 키가 있다 (형식: 이름=키,이름2=키2)")
        out[key] = name or hashlib.sha256(key.encode()).hexdigest()[:8]
    return out


def presented_key(headers: Mapping[str, str]) -> str | None:
    """클라이언트가 낸 키. `Authorization: Bearer x` 또는 `x-api-key: x`."""
    auth = headers.get("authorization", "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return auth[7:].strip()
    key = headers.get("x-api-key", "")
    return key.strip() or None


class Auth:
    def __init__(self, client_keys: dict[str, str] | None, upstream_key: str | None = None) -> None:
        self.client_keys = client_keys            # None = 무인증(GATEWAY_AUTH=off)
        self.upstream_key = upstream_key or None

    @property
    def enabled(self) -> bool:
        return self.client_keys is not None

    def client_of(self, headers: Mapping[str, str]) -> str | None:
        """낸 키가 맞으면 클라이언트 이름, 아니면 None. 무인증이면 None(그래도 통과시킨다)."""
        if not self.enabled:
            return None
        key = presented_key(headers)
        if key is None:
            return None
        for known, name in self.client_keys.items():
            if hmac.compare_digest(known.encode(), key.encode()):
                return name
        return None

    def upstream_headers(self, path: str, pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
        """상류로 보낼 헤더. 상류 키가 있으면 클라이언트의 인증 헤더를 떼고 상류 형식으로 단다."""
        if not self.upstream_key:
            return list(pairs)
        kept = [(k, v) for k, v in pairs if k.lower() not in AUTH_HEADERS]
        if path.startswith("/v1/messages"):
            kept.append(("x-api-key", self.upstream_key))
        else:
            kept.append(("authorization", f"Bearer {self.upstream_key}"))
        return kept
