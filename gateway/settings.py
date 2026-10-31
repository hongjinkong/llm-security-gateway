"""게이트웨이 설정(D-118) — 환경변수를 한 번 읽어 `Settings`로 만들고, 그 설정으로 검사기 체인을 조립한다.

앱은 `gateway.main.create_app(settings)`로 만든다. import 시점 전역이 없으므로 한 프로세스에 설정이 다른 게이트웨이를 여럿 띄울 수 있다(테스트 하네스).
`.env`는 읽지 않는다 — `uvicorn --env-file .env`로 넘긴다. 고르는 값·종류·역할의 틀린 값은 여기서 ValueError다.
기동 거부(클라이언트 키 없음, 무인증 + 상류 키, mask인데 대체값 키 없음)는 lifespan이 한다 — import만으로는 실패하지 않는다.

D-119: `GATEWAY_CONFIG`(TOML)가 있으면 `[[clients]]`(해시 키·정책)·`[policies.<이름>]`·`[upstreams.<api>]`를 더 읽는다. 공급자 키는 파일에 두지 않고
`key_env`가 가리키는 환경변수에서 읽는다. 클라이언트 키는 SHA-256으로만 든다(환경변수의 평문 키도 읽을 때 해시한다).
"""
from __future__ import annotations

import hashlib
import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from gateway.auth import parse_client_keys
from gateway.chain import DetectorChain
from gateway.detectors.base import Detector
from gateway.detectors.injection import InjectionRuleDetector
from gateway.detectors.pii import ALL_KINDS, DETECT_ONLY, PIIDetector
from gateway import messages
from gateway.messages import LANGS, ConfigError
from gateway.openai_api import PII_ROLES
from gateway.vault import TokenVault

INJECTION_MODES = ("observe", "block", "off")
PII_MODES = ("mask", "detect", "off")
API_NAMES = ("chat", "responses", "messages")     # 상류를 고르는 이름 = 어댑터 이름(D-119)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Upstream:
    base_url: str
    key: str = ""          # 공급자 키 — 환경변수에서 읽은 값. 설정 파일에는 환경변수 이름(key_env)만 있다
    timeout: float = 600.0


@dataclass(frozen=True)
class Client:
    name: str
    policy: str = "default"


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class Settings:
    target_url: str = "http://localhost:8000"            # TARGET_URL — 상류 origin. 기본 8000은 로컬 스텁·OpenAI 호환 서버
    timeout: float = 600.0                               # GATEWAY_TIMEOUT — 상류 읽기 대기(초, D-023)
    log_path: str = "logs/gateway.jsonl"                 # GATEWAY_LOG_PATH — `-`면 stdout(D-107 E)
    log_max_bytes: int = 100 * 1024 * 1024               # GATEWAY_LOG_MAX_BYTES
    log_backups: int = 5                                 # GATEWAY_LOG_BACKUPS
    rate_per_minute: int = 0                             # GATEWAY_RATE_PER_MINUTE — 0 = 끔
    admin_key: str = ""                                  # GATEWAY_ADMIN_KEY — info·metrics를 연다(D-109). 없으면 둘 다 404
    # 차단 문구. 어댑터가 그 API의 정상 응답 모양(HTTP 200)에 싣는다 — 클라이언트 SDK가 오류로 다루지 않는다
    blocked_message: str = ""                            # GATEWAY_BLOCKED_MESSAGE — 비우면 카탈로그(GATEWAY_LANG)의 문구
    lang: str = "ko"                                     # GATEWAY_LANG — ko|en, 사용자·운영자 문구(D-120)
    max_body_bytes: int = 1024 * 1024                    # GATEWAY_MAX_BODY_BYTES — 넘으면 413(D-099)
    max_findings: int = 5000                             # GATEWAY_MAX_FINDINGS — mask 모드 한 요청의 탐지 상한(D-110)
    # 결정적 대체값 키(D-111). 이 키와 대체값이 있으면 원문을 되짚을 수 있으므로 클라이언트 키·공급자 키와 같은 등급으로 보관한다
    surrogate_key: str = ""                              # GATEWAY_SURROGATE_KEY
    max_connections: int = 100                           # GATEWAY_MAX_CONNECTIONS — 상류 연결 풀(D-110)
    auth_off: bool = False                               # GATEWAY_AUTH=off — 로컬 실험만(D-107 A)
    # 키의 SHA-256 → 클라이언트(D-119). GATEWAY_CLIENT_KEYS `이름=키,…`(평문을 읽을 때 해시, 정책 default)와 설정 파일 [[clients]]
    clients: Mapping[str, Client] = field(default_factory=dict)
    upstream_key: str = ""                               # GATEWAY_UPSTREAM_KEY — 설정 파일에 없는 상류의 공급자 키
    injection: str = "observe"                           # GATEWAY_INJECTION — observe|block|off
    pii: str = "mask"                                    # GATEWAY_PII — mask|detect|off
    pii_kinds: tuple[str, ...] = ALL_KINDS               # GATEWAY_PII_KINDS
    pii_detect_kinds: tuple[str, ...] = DETECT_ONLY      # GATEWAY_PII_DETECT_KINDS — 가리지 않고 감사에만(D-117)
    pii_roles: frozenset[str] = PII_ROLES                # GATEWAY_PII_ROLES — developer는 system의 별칭(D-112)
    # 저수준 검사기 목록 — 있으면 injection·pii보다 우선, 빈 튜플은 검사기 없음. 환경변수가 없다(테스트·임베딩용, D-118)
    detectors: tuple[str, ...] | None = None
    allowed_models: tuple[str, ...] | None = None        # 정책의 허용 모델(fnmatch 글롭, D-119). None = 모두
    upstreams: Mapping[str, Upstream] = field(default_factory=dict)   # 설정 파일의 [upstreams.<api>]. 없는 api는 upstream()이 기본값
    policies: Mapping[str, Settings] = field(default_factory=dict)    # default 밖의 정책 — 정책마다 검사기 설정만 다르다
    config_version: str | None = None                    # 설정 파일 SHA-256 앞 12자

    def upstream(self, api: str) -> Upstream:
        """그 API의 상류. 설정 파일에 없으면 TARGET_URL·GATEWAY_UPSTREAM_KEY·GATEWAY_TIMEOUT(하위 호환)."""
        return self.upstreams.get(api) or Upstream(self.target_url, self.upstream_key, self.timeout)

    def policy_settings(self) -> dict[str, Settings]:
        """정책 이름 → 그 정책의 설정. `default`는 늘 있다(이 설정 자신)."""
        return {"default": self, **self.policies}

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        """설정 오류는 GATEWAY_LANG의 문장으로 ValueError가 된다(D-120)."""
        lang = env.get("GATEWAY_LANG", "ko").strip().lower()
        try:
            return cls._from_env(env, _choice("GATEWAY_LANG", lang, LANGS))
        except ConfigError as exc:
            raise ValueError(exc.render(lang if lang in LANGS else "ko")) from None

    @classmethod
    def _from_env(cls, env: Mapping[str, str], lang: str) -> Settings:
        def get(name: str, default: str) -> str:
            return env.get(name, default).strip()

        auth_off = get("GATEWAY_AUTH", "").lower() == "off"
        plain = {} if auth_off else parse_client_keys(env.get("GATEWAY_CLIENT_KEYS", ""))
        base = cls(
            target_url=get("TARGET_URL", cls.target_url).rstrip("/"),
            timeout=float(get("GATEWAY_TIMEOUT", "600")),
            log_path=get("GATEWAY_LOG_PATH", cls.log_path),
            log_max_bytes=int(get("GATEWAY_LOG_MAX_BYTES", str(cls.log_max_bytes))),
            log_backups=int(get("GATEWAY_LOG_BACKUPS", str(cls.log_backups))),
            rate_per_minute=int(get("GATEWAY_RATE_PER_MINUTE", "0")),
            admin_key=env.get("GATEWAY_ADMIN_KEY", ""),
            blocked_message=env.get("GATEWAY_BLOCKED_MESSAGE", ""),
            lang=lang,
            max_body_bytes=int(get("GATEWAY_MAX_BODY_BYTES", str(cls.max_body_bytes))),
            max_findings=int(get("GATEWAY_MAX_FINDINGS", str(cls.max_findings))),
            surrogate_key=env.get("GATEWAY_SURROGATE_KEY", ""),
            max_connections=int(get("GATEWAY_MAX_CONNECTIONS", str(cls.max_connections))),
            auth_off=auth_off,
            clients={key_hash(key): Client(name) for key, name in plain.items()},
            upstream_key=env.get("GATEWAY_UPSTREAM_KEY", ""),
            injection=_choice("GATEWAY_INJECTION", get("GATEWAY_INJECTION", "observe").lower(), INJECTION_MODES),
            pii=_choice("GATEWAY_PII", get("GATEWAY_PII", "mask").lower(), PII_MODES),
            pii_kinds=_kinds(env, "GATEWAY_PII_KINDS", ALL_KINDS),
            pii_detect_kinds=_kinds(env, "GATEWAY_PII_DETECT_KINDS", DETECT_ONLY),
            pii_roles=_roles(env.get("GATEWAY_PII_ROLES")),
        )
        path = env.get("GATEWAY_CONFIG", "").strip()
        return _with_config(base, Path(path), env) if path else base


# --- 설정 파일(D-119) ---------------------------------------------------------------
POLICY_KEYS = {"injection", "pii_mode", "pii_kinds", "pii_detect_kinds", "pii_roles", "allowed_models"}


def _with_config(base: Settings, path: Path, env: Mapping[str, str]) -> Settings:
    raw = path.read_bytes()
    where = f"GATEWAY_CONFIG {path}"
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError("config_parse", where=where, error=exc) from exc
    _only(doc, {"clients", "policies", "upstreams"}, where)
    tables = doc.get("policies", {})
    _table(tables, where, "policies")
    if "default" in tables:                          # 기본 정책을 고치면 다른 정책도 그것을 따른다
        base = _policy(base, tables["default"], f"{where} [policies.default]")
    policies = {name: replace(_policy(base, t, f"{where} [policies.{name}]"), policies={})
                for name, t in tables.items() if name != "default"}
    upstreams = {}
    for api, t in _table(doc.get("upstreams", {}), where, "upstreams").items():
        if api not in API_NAMES:
            raise ConfigError("upstream_api", where=where, api=api, apis="|".join(API_NAMES))
        _only(t, {"base_url", "key_env", "timeout"}, f"{where} [upstreams.{api}]")
        key_env = _str(t.get("key_env", ""), f"{where} [upstreams.{api}] key_env")
        if key_env and key_env not in env:
            raise ConfigError("key_env_missing", where=f"{where} [upstreams.{api}]", key_env=key_env)
        # key_env가 없으면 공급자 키를 달지 않는다 — GATEWAY_UPSTREAM_KEY(다른 공급자의 키일 수 있다)를 넘겨받지 않는다
        upstreams[api] = Upstream(_str(t.get("base_url", base.target_url), f"{where} [upstreams.{api}] base_url").rstrip("/"),
                                  env.get(key_env, "") if key_env else "", float(t.get("timeout", base.timeout)))
    clients = dict(base.clients)
    known = {"default", *policies}
    items = doc.get("clients", [])
    if not isinstance(items, list):
        raise ConfigError("clients_array", where=where)
    for i, t in enumerate(items):
        at = f"{where} [[clients]] {i + 1}"
        _only(t, {"name", "key_sha256", "policy"}, at)
        digest, name = _str(t.get("key_sha256", ""), at), _str(t.get("name", ""), at)
        policy = _str(t.get("policy", "default"), at)
        if not SHA256_RE.fullmatch(digest) or not name:
            raise ConfigError("client_fields", where=where, n=i + 1)
        if policy not in known:
            raise ConfigError("unknown_policy", where=where, n=i + 1, policy=policy)
        if digest in clients:
            raise ConfigError("duplicate_key", where=where, n=i + 1)
        clients[digest] = Client(name, policy)
    policies = {name: replace(policy, upstreams=upstreams) for name, policy in policies.items()}   # 볼트 TTL이 상류 시간 제한을 따른다
    return replace(base, clients=clients, upstreams=upstreams, policies=policies,
                   config_version=hashlib.sha256(raw).hexdigest()[:12])


def _policy(base: Settings, t: Any, where: str) -> Settings:
    _only(t, POLICY_KEYS, where)
    changes: dict[str, Any] = {}
    if "injection" in t:
        changes["injection"] = _choice(f"{where} injection", _str(t["injection"], where).lower(), INJECTION_MODES)
    if "pii_mode" in t:
        changes["pii"] = _choice(f"{where} pii_mode", _str(t["pii_mode"], where).lower(), PII_MODES)
    for key in ("pii_kinds", "pii_detect_kinds"):
        if key in t:
            changes[key] = _kind_list(f"{where} {key}", _strs(t[key], where))
    if "pii_roles" in t:
        changes["pii_roles"] = _roles(",".join(_strs(t["pii_roles"], where)))
    if "allowed_models" in t:
        changes["allowed_models"] = tuple(_strs(t["allowed_models"], where))
    return replace(base, **changes)


def _only(t: Any, allowed: set[str], where: str) -> None:
    if not isinstance(t, dict):
        raise ConfigError("not_table", where=where)
    if set(t) - allowed:
        raise ConfigError("unknown_keys", where=where, unknown=sorted(set(t) - allowed), allowed=sorted(allowed))


def _table(t: Any, where: str, name: str) -> dict:
    if not isinstance(t, dict) or not all(isinstance(v, dict) for v in t.values()):
        raise ConfigError("named_tables", where=where, name=name)
    return t


def _str(v: Any, where: str) -> str:
    if not isinstance(v, str):
        raise ConfigError("not_str", where=where, value=v)
    return v.strip()


def _strs(v: Any, where: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError("not_strs", where=where, value=v)
    return [x.strip() for x in v if x.strip()]


def _choice(var: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ConfigError("choice", var=var, allowed="|".join(allowed), value=value)
    return value


def _kinds(env: Mapping[str, str], var: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """쉼표 목록. 모르는 이름은 ValueError(D-117)."""
    spec = env.get(var)
    return default if spec is None else _kind_list(var, spec.split(","))


def _kind_list(where: str, items: list[str]) -> tuple[str, ...]:
    kinds = tuple(x.strip().lower() for x in items if x.strip())
    if set(kinds) - set(ALL_KINDS):
        raise ConfigError("kinds", where=where, kinds=list(ALL_KINDS), items=items)
    return kinds


def _roles(spec: str | None) -> frozenset[str]:
    """가리는 역할을 좁힌다(D-112). 기본은 전부. developer는 system의 별칭. 모르는 이름은 ValueError."""
    if spec is None:
        return PII_ROLES
    roles = frozenset({"developer": "system"}.get(x, x) for x in (y.strip().lower() for y in spec.split(",")) if x)
    if not roles or roles - PII_ROLES:
        raise ConfigError("roles", roles=sorted(PII_ROLES), spec=spec)
    return roles


def detector_names(settings: Settings) -> list[str]:
    """체인 순서는 고정이다: injection → pii(D-107 D). 차단은 늘 이번 턴만 본다(D-118 — 이력까지 보는 차단은 제품 설정에서 뺐다)."""
    if settings.detectors is not None:
        return list(settings.detectors)
    names = {"observe": ["injection_observe"], "block": ["injection_rule_turn"], "off": []}[settings.injection]
    return names + {"mask": ["pii_mask"], "detect": ["pii"], "off": []}[settings.pii]


# 이름 → 생성자(설정을 받는다). 테스트는 tests/chain_app.py에서 시험용 검사기를 더한 사전을 넘긴다.
Registry = Mapping[str, Callable[[Settings], Detector]]
DETECTOR_REGISTRY: Registry = {
    "pii": lambda s: PIIDetector("detect", kinds=s.pii_kinds, roles=s.pii_roles),
    # 볼트 TTL은 상류 타임아웃보다 길다 — 긴 스트림 도중 매핑이 만료되면 복원이 깨진다(D-110).
    "pii_mask": lambda s: PIIDetector("mask", kinds=s.pii_kinds, max_findings=s.max_findings, roles=s.pii_roles,
                                      detect_kinds=s.pii_detect_kinds,
                                      vault=TokenVault(ttl=max(s.upstream(a).timeout for a in API_NAMES) + 60,
                                                       key=s.surrogate_key.encode() or None)),
    "injection_observe": lambda s: InjectionRuleDetector(mode="observe"),
    "injection_rule": lambda s: InjectionRuleDetector(),           # 이력까지 본다 — 제품 설정에는 없다(테스트용)
    "injection_rule_turn": lambda s: InjectionRuleDetector(scope="turn", redacted=messages.t("redacted_turn", s.lang)),
}


def build_chain(settings: Settings, registry: Registry = DETECTOR_REGISTRY) -> DetectorChain:
    names = detector_names(settings)
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise ValueError(f"알 수 없는 검사기: {unknown}. 등록된 것: {sorted(registry)}")
    return DetectorChain([registry[n](settings) for n in names])
