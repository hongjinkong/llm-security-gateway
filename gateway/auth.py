"""클라이언트 인증과 상류 키 보관(D-107 A).

키 모델: 클라이언트는 **게이트웨이 키**를 들고, 공급자(상류) 키는 게이트웨이 환경변수 하나에만 있다.
  GATEWAY_CLIENT_KEYS="이름=키,이름2=키2"   이름을 빼면 키 지문(sha256) 앞 8자리가 이름이다. 없으면 기동 실패 — 닫힌 채로 시작한다.
  GATEWAY_AUTH=off                       로컬 실험용으로만 무인증을 연다(명시해야 한다).
  GATEWAY_UPSTREAM_KEY=…                 있으면 상류 형식으로 단다. GATEWAY_AUTH=off와 함께 쓰면 기동 실패(D-109).

클라이언트는 `Authorization: Bearer <키>`(OpenAI SDK)나 `x-api-key: <키>`(Anthropic SDK)로 낸다. 상류에는 Anthropic 형식 요청
(`/v1/messages*`이거나 `anthropic-version`을 보낸 요청 — Anthropic SDK의 `GET /v1/models`)이면 `x-api-key`, 그 밖에는
`Authorization: Bearer`로 단다(Anthropic의 OpenAI 호환 입구도 Bearer를 받는다, D-103).

상류로 넘기는 요청 헤더는 허용 목록뿐이다(D-109). 클라이언트의 인증 헤더는 게이트웨이 인증이 꺼져 있을 때만 넘긴다 —
켜져 있으면 그것은 게이트웨이 키라 상류(제3자)에 보내지 않는다. 상류 키가 없는 통과 모드에서는 클라이언트 자신의
공급자 계정을 가리키는 `openai-organization`·`openai-project`도 넘긴다.

D-119: 클라이언트 키는 SHA-256으로만 든다 — 설정 파일 `[[clients]] key_sha256`, 환경변수의 평문 키는 읽을 때 해시한다(settings.py).
비교는 낸 키의 해시와 모든 항목을 `hmac.compare_digest`로. 공급자 키는 상류마다 다를 수 있어 `upstream_headers`가 받는다.
키 생성: `python -m gateway keygen`(설정 파일용은 `--hash`).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable, Mapping
from typing import Generic, TypeVar

from gateway.messages import ConfigError

C = TypeVar("C")

AUTH_HEADERS = frozenset({"authorization", "x-api-key"})
# 상류로 넘기는 요청 헤더(D-109). 그 밖(cookie·x-forwarded-*·hop-by-hop·host·content-length·accept-encoding·SDK 계측 헤더)은 전부 뗀다.
PASS_HEADERS = frozenset({"content-type", "accept", "user-agent", "anthropic-version", "anthropic-beta",
                          "openai-beta", "idempotency-key"})
PASSTHROUGH_HEADERS = frozenset({"openai-organization", "openai-project"})   # 상류 키가 없을 때만


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
            raise ConfigError("empty_client_key")
        out[key] = name or hashlib.sha256(key.encode()).hexdigest()[:8]
    return out


def presented_key(headers: Mapping[str, str]) -> str | None:
    """클라이언트가 낸 키. `Authorization: Bearer x` 또는 `x-api-key: x`."""
    auth = headers.get("authorization", "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return auth[7:].strip()
    key = headers.get("x-api-key", "")
    return key.strip() or None


class Auth(Generic[C]):
    def __init__(self, clients: Mapping[str, C] | None) -> None:
        self.clients = clients                    # 키의 SHA-256 → 클라이언트. None = 무인증(GATEWAY_AUTH=off)

    @property
    def enabled(self) -> bool:
        return self.clients is not None

    def client_of(self, headers: Mapping[str, str]) -> C | None:
        """낸 키가 맞으면 그 클라이언트, 아니면 None. 무인증이면 None(그래도 통과시킨다)."""
        if self.clients is None:                  # 무인증
            return None
        key = presented_key(headers)
        if key is None:
            return None
        digest = hashlib.sha256(key.encode()).hexdigest().encode()
        found = None
        for known, client in self.clients.items():   # 맞는 것을 찾아도 끝까지 본다 — 비교 횟수가 키 순서를 드러내지 않게
            if hmac.compare_digest(known.encode(), digest):
                found = client
        return found

    def upstream_headers(self, path: str, pairs: Iterable[tuple[str, str]], upstream_key: str | None) -> list[tuple[str, str]]:
        """상류로 보낼 헤더(D-109). 허용 목록만 넘기고, 그 상류의 공급자 키가 있으면 상류 형식으로 단다(D-119 상류마다)."""
        pairs = list(pairs)
        if not upstream_key:
            allowed = PASS_HEADERS | PASSTHROUGH_HEADERS | (frozenset() if self.enabled else AUTH_HEADERS)
            return [(k, v) for k, v in pairs if k.lower() in allowed]
        kept = [(k, v) for k, v in pairs if k.lower() in PASS_HEADERS]
        if path.startswith("/v1/messages") or any(k.lower() == "anthropic-version" for k, _ in pairs):
            kept.append(("x-api-key", upstream_key))
        else:
            kept.append(("authorization", f"Bearer {upstream_key}"))
        return kept
