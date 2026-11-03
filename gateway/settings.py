"""게이트웨이 설정(D-118) — 환경변수를 한 번 읽어 `Settings`로 만들고, 그 설정으로 검사기 체인을 조립한다.

앱은 `gateway.main.create_app(settings)`로 만든다. import 시점 전역이 없으므로 한 프로세스에 설정이 다른 게이트웨이를 여럿 띄울 수 있다(테스트 하네스).
`.env`는 읽지 않는다 — `uvicorn --env-file .env`로 넘긴다. 고르는 값·종류·역할의 틀린 값은 여기서 ValueError다.
기동 거부(클라이언트 키 없음, 무인증 + 상류 키, mask인데 대체값 키 없음)는 lifespan이 한다 — import만으로는 실패하지 않는다.

D-119: `GATEWAY_CONFIG`(TOML)가 있으면 `[[clients]]`(해시 키·정책)·`[policies.<이름>]`·`[upstreams.<api>]`를 더 읽는다. 공급자 키는 파일에 두지 않고
`key_env`가 가리키는 환경변수에서 읽는다. 클라이언트 키는 SHA-256으로만 든다(환경변수의 평문 키도 읽을 때 해시한다).
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from gateway.auth import parse_client_keys
from gateway.chain import DetectorChain
from gateway.detectors.base import Detector
from gateway.detectors.guard import FAIL_MODES as GUARD_FAIL, GuardDetector
from gateway.detectors.injection import InjectionRuleDetector
from gateway.detect_client import DetectClient
from gateway.detectors.patterns import NER_KINDS
from gateway.detectors.pii import ALL_KINDS, DETECT_ONLY, FAIL_MODES, REGEX_KINDS, PIIDetector
from gateway import messages
from gateway.messages import LANGS, ConfigError
from gateway.openai_api import PII_ROLES
from gateway.vault import TokenVault

INJECTION_MODES = ("observe", "block", "off")
GUARD_MODES = ("off", "observe", "block")
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
    admin_key: str = ""                                  # GATEWAY_ADMIN_KEY — info·metrics·stats·대시보드를 연다(D-109·D-124). 없으면 모두 404
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
    pii_kinds: tuple[str, ...] = REGEX_KINDS             # GATEWAY_PII_KINDS — 기본은 정규식 12종. person·address·org(D-126)는 정책이 더해 켠다
    pii_detect_kinds: tuple[str, ...] = DETECT_ONLY      # GATEWAY_PII_DETECT_KINDS — 가리지 않고 감사에만(D-117)
    pii_roles: frozenset[str] = PII_ROLES                # GATEWAY_PII_ROLES — developer는 system의 별칭(D-112)
    detect_url: str = ""                                 # GATEWAY_DETECT_URL — 탐지 사이드카(detect/) 주소. 비면 NER 없음(D-126)
    detect_timeout: float = 10.0                         # GATEWAY_DETECT_TIMEOUT — 한 요청의 NER 전체 기한(초)
    detect_fail: str = "closed"                          # GATEWAY_DETECT_FAIL — closed(503 detect_unavailable)|open(정규식 종류만 가리고 보냄)
    guard: str = "off"                                   # GATEWAY_GUARD — off|observe|block, 가드레일 웹훅(D-127, 정책 키 guard)
    guard_url: str = ""                                  # GATEWAY_GUARD_URL — 웹훅 주소(사이드카면 …/v1/guard)
    guard_timeout: float = 5.0                           # GATEWAY_GUARD_TIMEOUT — 한 요청의 웹훅 전체 기한(초)
    guard_fail: str = "open"                             # GATEWAY_GUARD_FAIL — open(판정 없이 통과)|closed(block 모드에서 503 guard_unavailable)
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
            return env.get(name, default).strip()     # 키 값도 — secret.env·`$(cat 파일)`의 줄 끝 공백이 키에 붙지 않게(D-122)

        auth_off = get("GATEWAY_AUTH", "").lower() == "off"
        plain = {} if auth_off else parse_client_keys(env.get("GATEWAY_CLIENT_KEYS", ""))
        base = cls(
            target_url=get("TARGET_URL", cls.target_url).rstrip("/"),
            timeout=float(get("GATEWAY_TIMEOUT", "600")),
            log_path=get("GATEWAY_LOG_PATH", cls.log_path),
            log_max_bytes=int(get("GATEWAY_LOG_MAX_BYTES", str(cls.log_max_bytes))),
            log_backups=int(get("GATEWAY_LOG_BACKUPS", str(cls.log_backups))),
            rate_per_minute=int(get("GATEWAY_RATE_PER_MINUTE", "0")),
            admin_key=get("GATEWAY_ADMIN_KEY", ""),
            blocked_message=env.get("GATEWAY_BLOCKED_MESSAGE", ""),
            lang=lang,
            max_body_bytes=int(get("GATEWAY_MAX_BODY_BYTES", str(cls.max_body_bytes))),
            max_findings=int(get("GATEWAY_MAX_FINDINGS", str(cls.max_findings))),
            surrogate_key=get("GATEWAY_SURROGATE_KEY", ""),
            max_connections=int(get("GATEWAY_MAX_CONNECTIONS", str(cls.max_connections))),
            auth_off=auth_off,
            clients={key_hash(key): Client(name) for key, name in plain.items()},
            upstream_key=get("GATEWAY_UPSTREAM_KEY", ""),
            injection=_choice("GATEWAY_INJECTION", get("GATEWAY_INJECTION", "observe").lower(), INJECTION_MODES),
            pii=_choice("GATEWAY_PII", get("GATEWAY_PII", "mask").lower(), PII_MODES),
            pii_kinds=_kinds(env, "GATEWAY_PII_KINDS", REGEX_KINDS),
            pii_detect_kinds=_kinds(env, "GATEWAY_PII_DETECT_KINDS", DETECT_ONLY),
            pii_roles=_roles(env.get("GATEWAY_PII_ROLES")),
            detect_url=_url("GATEWAY_DETECT_URL", get("GATEWAY_DETECT_URL", "")),
            detect_timeout=_positive("GATEWAY_DETECT_TIMEOUT", get("GATEWAY_DETECT_TIMEOUT", "10")),
            detect_fail=_choice("GATEWAY_DETECT_FAIL", get("GATEWAY_DETECT_FAIL", "closed").lower(), FAIL_MODES),
            guard=_choice("GATEWAY_GUARD", get("GATEWAY_GUARD", "off").lower(), GUARD_MODES),
            guard_url=_url("GATEWAY_GUARD_URL", get("GATEWAY_GUARD_URL", ""), path=True),
            guard_timeout=_positive("GATEWAY_GUARD_TIMEOUT", get("GATEWAY_GUARD_TIMEOUT", "5")),
            guard_fail=_choice("GATEWAY_GUARD_FAIL", get("GATEWAY_GUARD_FAIL", "open").lower(), GUARD_FAIL),
        )
        path = env.get("GATEWAY_CONFIG", "").strip()
        return _with_config(base, Path(path), env) if path else base


# --- 설정 파일(D-119) ---------------------------------------------------------------
# 표마다 쓸 수 있는 키 — 문서의 설정 키 표가 이것과 같은지 테스트가 본다(D-121)
CLIENT_KEYS = {"name", "key_sha256", "policy"}
POLICY_KEYS = {"injection", "pii_mode", "pii_kinds", "pii_detect_kinds", "pii_roles", "allowed_models", "guard"}
UPSTREAM_KEYS = {"base_url", "key_env", "timeout"}


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
        _only(t, UPSTREAM_KEYS, f"{where} [upstreams.{api}]")
        key_env = _str(t.get("key_env", ""), f"{where} [upstreams.{api}] key_env")
        if key_env and not env.get(key_env, "").strip():   # 빈 값도 — 키 없이 보내면 요청마다 상류 401로만 드러난다(D-121)
            raise ConfigError("key_env_missing", where=f"{where} [upstreams.{api}]", key_env=key_env)
        # key_env가 없으면 공급자 키를 달지 않는다 — GATEWAY_UPSTREAM_KEY(다른 공급자의 키일 수 있다)를 넘겨받지 않는다
        upstreams[api] = Upstream(_str(t.get("base_url", base.target_url), f"{where} [upstreams.{api}] base_url").rstrip("/"),
                                  env[key_env].strip() if key_env else "", float(t.get("timeout", base.timeout)))
    clients = dict(base.clients)
    known = {"default", *policies}
    items = doc.get("clients", [])
    if not isinstance(items, list):
        raise ConfigError("clients_array", where=where)
    for i, t in enumerate(items):
        at = f"{where} [[clients]] {i + 1}"
        _only(t, CLIENT_KEYS, at)
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
    if "guard" in t:
        changes["guard"] = _choice(f"{where} guard", _str(t["guard"], where).lower(), GUARD_MODES)
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


def _positive(var: str, value: str) -> float:
    """0보다 큰 유한한 초(D-126 리뷰) — 0·음수·nan·글자는 기동 거부. 0이면 모든 호출이 timeout이 되고 nan은 요청마다 500이다."""
    try:
        seconds = float(value)
    except ValueError:
        seconds = float("nan")
    if not (seconds > 0 and math.isfinite(seconds)):
        raise ConfigError("positive", var=var, value=value)
    return seconds


def _url(var: str, value: str, path: bool = False) -> str:
    """`http(s)://호스트[:포트]` 모양만(D-126 리뷰) — 경로·쿼리가 붙으면 `/v1/detect`가 그 뒤에 붙어 404가 되고, 스킴이 없으면 첫 요청에서야 connect로 드러난다.
    웹훅(GATEWAY_GUARD_URL, D-127)은 주소 그대로 부르므로 경로를 받는다. 쿼리·조각은 어느 쪽도 받지 않는다(info에 그대로 보인다)."""
    if not value:
        return ""
    u = urllib.parse.urlsplit(value)
    try:
        port_ok = u.port is None or 0 < u.port      # 숫자가 아니거나 범위 밖이면 ValueError — 놓아두면 요청마다 InvalidURL·OverflowError로 500이다(D-127 리뷰)
    except ValueError:
        port_ok = False
    if (u.scheme not in ("http", "https") or not u.hostname or not port_ok or u.username is not None or u.password is not None
            or (not path and u.path not in ("", "/")) or u.query or u.fragment):     # 사용자 정보(user:token@)도 받지 않는다 — info에 그대로 보인다
        raise ConfigError("url", var=var, value=value, form="http(s)://host[:port]" + ("[/path]" if path else ""))
    return value if path else value.rstrip("/")


def _roles(spec: str | None) -> frozenset[str]:
    """가리는 역할을 좁힌다(D-112). 기본은 전부. developer는 system의 별칭. 모르는 이름은 ValueError."""
    if spec is None:
        return PII_ROLES
    roles = frozenset({"developer": "system"}.get(x, x) for x in (y.strip().lower() for y in spec.split(",")) if x)
    if not roles or roles - PII_ROLES:
        raise ConfigError("roles", roles=sorted(PII_ROLES), spec=spec)
    return roles


def ner_policies(settings: Settings) -> list[str]:
    """이름·주소·직장(NER 종류, D-126)을 켠 정책 이름 — pii_mode가 off가 아닌 것만. 비어 있지 않은데 GATEWAY_DETECT_URL이 없으면 기동 거부(main)."""
    return [name for name, p in settings.policy_settings().items() if p.pii != "off" and set(p.pii_kinds) & set(NER_KINDS)]


def guard_policies(settings: Settings) -> list[str]:
    """가드레일 웹훅(D-127)을 켠 정책 이름. 비어 있지 않은데 GATEWAY_GUARD_URL이 없으면 기동 거부(main)."""
    return [name for name, p in settings.policy_settings().items() if p.guard != "off"]


def _detect(s: Settings) -> DetectClient | None:
    """정책이 NER 종류를 켰고 사이드카 주소가 있을 때만 클라이언트(캐시는 검사기마다, D-126)."""
    return DetectClient(s.detect_url, s.detect_timeout) if s.detect_url and set(s.pii_kinds) & set(NER_KINDS) else None


def detector_names(settings: Settings) -> list[str]:
    """체인 순서는 고정이다: injection → pii(D-107 D) → 가드레일(D-127 — PII 뒤라 웹훅은 공급자와 같은 텍스트를 본다). 차단은 늘 이번 턴만 본다(D-118 — 이력까지 보는 차단은 제품 설정에서 뺐다)."""
    if settings.detectors is not None:
        return list(settings.detectors)
    names = {"observe": ["injection_observe"], "block": ["injection_rule_turn"], "off": []}[settings.injection]
    return (names + {"mask": ["pii_mask"], "detect": ["pii"], "off": []}[settings.pii]
            + {"observe": ["injection_guard"], "block": ["injection_guard_block"], "off": []}[settings.guard])


# 이름 → 생성자(설정을 받는다). 테스트는 tests/chain_app.py에서 시험용 검사기를 더한 사전을 넘긴다.
Registry = Mapping[str, Callable[[Settings], Detector]]
DETECTOR_REGISTRY: Registry = {
    "pii": lambda s: PIIDetector("detect", kinds=s.pii_kinds, roles=s.pii_roles, detect=_detect(s)),
    # 볼트 TTL은 상류 타임아웃보다 길다 — 긴 스트림 도중 매핑이 만료되면 복원이 깨진다(D-110).
    "pii_mask": lambda s: PIIDetector("mask", kinds=s.pii_kinds, max_findings=s.max_findings, roles=s.pii_roles,
                                      detect_kinds=s.pii_detect_kinds, detect=_detect(s), detect_fail=s.detect_fail,
                                      vault=TokenVault(ttl=max(s.upstream(a).timeout for a in API_NAMES) + 60,
                                                       key=s.surrogate_key.encode() or None)),
    "injection_observe": lambda s: InjectionRuleDetector(mode="observe"),
    "injection_rule": lambda s: InjectionRuleDetector(),           # 이력까지 본다 — 제품 설정에는 없다(테스트용)
    "injection_rule_turn": lambda s: InjectionRuleDetector(scope="turn", redacted=messages.t("redacted_turn", s.lang)),
    "injection_guard": lambda s: GuardDetector(s.guard_url, "observe", s.guard_timeout, s.guard_fail),
    "injection_guard_block": lambda s: GuardDetector(s.guard_url, "block", s.guard_timeout, s.guard_fail),
}


def build_chain(settings: Settings, registry: Registry = DETECTOR_REGISTRY) -> DetectorChain:
    names = detector_names(settings)
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise ValueError(f"알 수 없는 검사기: {unknown}. 등록된 것: {sorted(registry)}")
    return DetectorChain([registry[n](settings) for n in names])
