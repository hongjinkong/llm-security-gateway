"""사용자·운영자에게 가는 문구(D-120) — `GATEWAY_LANG=ko`(기본)·`en`.

차단 문구·요청 ID 꼬리·가린 이력 자리표시(사용자), 기동 거부·설정 오류(운영자). API 오류 본문(`invalid or missing API key` 등)은 여기 없다 —
공급자 API처럼 영어로 두고 SDK가 읽는다. 설정 오류는 키와 인자를 담은 `ConfigError`로 던지고 `Settings.from_env`가 그 언어로 바꾼다.
"""
from __future__ import annotations

LANGS = ("ko", "en")

CATALOG: dict[str, dict[str, str]] = {
    # 사용자
    "blocked": {"ko": "요청이 보안 정책에 의해 차단되었습니다.", "en": "The request was blocked by the security policy."},
    "request_id": {"ko": "{message} (요청 ID: {id})", "en": "{message} (request ID: {id})"},
    "redacted_turn": {"ko": "[보안 정책에 의해 가려진 이전 메시지]", "en": "[earlier message hidden by the security policy]"},
    # 기동 거부
    "no_client_keys": {
        "ko": "GATEWAY_CLIENT_KEYS가 없다 — 클라이언트 키 없이는 기동하지 않는다(D-107 A). `python -m gateway keygen`으로 키를 만들어 넣거나, "
              "로컬 실험이면 GATEWAY_AUTH=off를 명시한다",
        "en": "GATEWAY_CLIENT_KEYS is empty — the gateway does not start without client keys. Create one with `python -m gateway keygen`, "
              "or set GATEWAY_AUTH=off explicitly for a local experiment"},
    "auth_off_with_key": {
        "ko": "GATEWAY_AUTH=off와 GATEWAY_UPSTREAM_KEY(또는 상류의 key_env)를 함께 쓸 수 없다 — 누구나 상류 키로 중계하게 된다(D-109)",
        "en": "GATEWAY_AUTH=off cannot be combined with GATEWAY_UPSTREAM_KEY (or an upstream key_env) — anyone could relay with the provider key"},
    "no_surrogate_key": {
        "ko": "GATEWAY_SURROGATE_KEY가 없거나 32자보다 짧다 — PII mask 모드는 결정적 대체값 키가 필요하다(D-111). `python -m gateway keygen`으로 만들어 넣는다",
        "en": "GATEWAY_SURROGATE_KEY is missing or shorter than 32 characters — PII mask mode needs a deterministic surrogate key. "
              "Create one with `python -m gateway keygen`"},
    # 설정 오류
    "choice": {"ko": "{var}는 {allowed} 중 하나여야 한다: {value!r}", "en": "{var} must be one of {allowed}: {value!r}"},
    "kinds": {"ko": "{where}는 {kinds} 중에서 고른다: {items!r}", "en": "{where}: choose from {kinds}: {items!r}"},
    "roles": {"ko": "GATEWAY_PII_ROLES는 {roles}(developer = system) 중에서 고른다: {spec!r}",
              "en": "GATEWAY_PII_ROLES: choose from {roles} (developer = system): {spec!r}"},
    "empty_client_key": {"ko": "GATEWAY_CLIENT_KEYS: 빈 키가 있다 (형식: 이름=키,이름2=키2)",
                         "en": "GATEWAY_CLIENT_KEYS: an empty key (format: name=key,name2=key2)"},
    "config_parse": {"ko": "{where}: {error}", "en": "{where}: {error}"},
    "not_table": {"ko": "{where}: 표여야 한다", "en": "{where}: must be a table"},
    "unknown_keys": {"ko": "{where}: 모르는 키 {unknown} — 쓸 수 있는 것 {allowed}", "en": "{where}: unknown keys {unknown} — allowed {allowed}"},
    "named_tables": {"ko": "{where}: [{name}.<이름>] 표여야 한다", "en": "{where}: must be [{name}.<name>] tables"},
    "not_str": {"ko": "{where}: 문자열이어야 한다 — {value!r}", "en": "{where}: must be a string — {value!r}"},
    "not_strs": {"ko": "{where}: 문자열 목록이어야 한다 — {value!r}", "en": "{where}: must be a list of strings — {value!r}"},
    "upstream_api": {"ko": "{where}: [upstreams.{api}] — api는 {apis} 중 하나", "en": "{where}: [upstreams.{api}] — api must be one of {apis}"},
    "key_env_missing": {"ko": "{where}: key_env {key_env}가 가리키는 환경변수가 없다",
                        "en": "{where}: environment variable {key_env} named by key_env is not set"},
    "clients_array": {"ko": "{where}: clients는 [[clients]] 표의 배열이다", "en": "{where}: clients must be an array of [[clients]] tables"},
    "client_fields": {"ko": "{where} [[clients]] {n}번째: name과 key_sha256(소문자 16진 64자, `python -m gateway keygen --hash`)이 필요하다",
                      "en": "{where} [[clients]] #{n}: name and key_sha256 (64 lowercase hex chars, `python -m gateway keygen --hash`) are required"},
    "unknown_policy": {"ko": "{where} [[clients]] {n}번째: 없는 정책 {policy!r}", "en": "{where} [[clients]] #{n}: unknown policy {policy!r}"},
    "duplicate_key": {"ko": "{where} [[clients]] {n}번째: 같은 키가 두 번 있다", "en": "{where} [[clients]] #{n}: the same key appears twice"},
}


def t(key: str, lang: str = "ko", **kw: object) -> str:
    return CATALOG[key][lang].format(**kw)


class ConfigError(ValueError):
    """설정 오류 — 키와 인자를 들고 있다가 그 언어의 문장이 된다. 그냥 str()이면 한국어."""

    def __init__(self, key: str, **kw: object) -> None:
        self.key, self.kw = key, kw
        super().__init__(t(key, "ko", **kw))

    def render(self, lang: str) -> str:
        return t(self.key, lang, **self.kw)
