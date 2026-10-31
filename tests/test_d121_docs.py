"""D-121(PLAN 14단계): 문서·배포 견본이 코드와 같은가 — 환경변수 이름, 설정 파일 키, 견본 설정·비밀 이름, 상대 링크, k8s와 이미지의 종료 시간."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from gateway.main import router
from gateway.settings import CLIENT_KEYS, POLICY_KEYS, UPSTREAM_KEYS, Settings

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README.en.md", "SECURITY.md", "docs/configuration.md", "docs/operations.md", "docs/api-compat.md"]
UVICORN = {"WEB_CONCURRENCY", "FORWARDED_ALLOW_IPS", "UVICORN_TIMEOUT_KEEP_ALIVE"}   # 이미지의 uvicorn이 읽는다 — 게이트웨이 코드가 아니다
K8S = ROOT / "deploy" / "k8s"


class Recorder(dict):
    """읽힌 이름을 기록하는 환경 — `Settings.from_env`가 실제로 읽는 변수를 잰다(코드에서 이름을 긁지 않는다)."""

    def __init__(self, *args: object, **kw: object) -> None:
        super().__init__(*args, **kw)
        self.read: set[str] = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.read.add(key)
        return super().__contains__(key)


def read_names() -> set[str]:
    env = Recorder()
    Settings.from_env(env)
    return env.read


def text(path: str | Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def env_file_names(path: str | Path) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text(path), re.M))


# ---------- S3 문서 = 코드 ----------

def test_s3_recorder_sees_every_setting():
    assert len(read_names()) == 22 and "GATEWAY_CONFIG" in read_names()


@pytest.mark.parametrize("path", ["docs/configuration.md", "README.en.md"])
def test_s3_env_tables_list_exactly_what_the_code_reads(path):
    names = set(re.findall(r"^\| `([A-Z][A-Z0-9_]*)` \|", text(path), re.M))
    assert names - UVICORN == read_names()
    assert UVICORN <= names


@pytest.mark.parametrize("path", DOCS)
def test_s3_docs_mention_only_real_variables(path):
    """지운 변수(D-118의 셋 등)가 문서에 남지 않는다."""
    # 경계는 ASCII로 본다 — `\b`는 한글도 단어 글자로 보아 `GATEWAY_X가`를 놓친다
    assert set(re.findall(r"(?<![A-Za-z0-9_])(?:GATEWAY|TARGET)_[A-Z0-9_]*[A-Z0-9](?![A-Za-z0-9_])", text(path))) <= read_names()


def test_s3_config_key_table_matches_code():
    rows = set(re.findall(r"^\| `\[\[?(clients|policies|upstreams)[^\]]*\]\]? (\w+)` \|", text("docs/configuration.md"), re.M))
    assert rows == ({("clients", k) for k in CLIENT_KEYS} | {("policies", k) for k in POLICY_KEYS}
                    | {("upstreams", k) for k in UPSTREAM_KEYS})


def test_s3_samples_use_real_names():
    real = read_names()
    key_envs = {t["key_env"] for t in tomllib.loads(text(K8S / "gateway.toml"))["upstreams"].values()}
    assert env_file_names(".env.example") <= real
    assert env_file_names(K8S / "secret.env.example") <= real | key_envs
    assert set(re.findall(r"^\s+([A-Z][A-Z0-9_]*): ", text("deploy/compose.yml"), re.M)) <= real   # environment:
    assert set(re.findall(r"- name: ([A-Z][A-Z0-9_]*)$", text(K8S / "gateway.yaml"), re.M)) <= real | UVICORN   # env:


def test_s3_k8s_config_loads_with_its_secret_and_not_without():
    config = {"GATEWAY_CONFIG": str(K8S / "gateway.toml")}
    names = env_file_names(K8S / "secret.env.example")
    s = Settings.from_env(config | {n: "x" * 40 for n in names})
    assert {api: u.base_url for api, u in s.upstreams.items()} == {
        "chat": "https://api.openai.com", "responses": "https://api.openai.com", "messages": "https://api.anthropic.com"}
    assert all(u.key for u in s.upstreams.values())          # 공급자 키는 모두 secret.env에서 온다
    with pytest.raises(ValueError, match="key_env"):          # 견본 그대로(빈 값)면 뜨지 않는다 — 요청마다 상류 401이 아니라 기동 실패
        Settings.from_env(config | {n: "" for n in names})


def slug(heading: str) -> str:
    """GitHub 머리글 앵커 — 소문자, 글자·숫자·공백·-·_ 밖은 지우고 공백은 -."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


@pytest.mark.parametrize("path", DOCS)
def test_s3_relative_links_resolve(path):
    base = (ROOT / path).parent
    broken = []
    for target, anchor in re.findall(r"\]\((?!https?://)([^)#\s]*)(?:#([^)\s]+))?\)", text(path)):
        file = (base / target) if target else ROOT / path
        if not file.exists():
            broken.append(target)
        elif anchor and file.suffix == ".md":
            anchors = {slug(h) for h in re.findall(r"^#+ (.+)$", file.read_text(encoding="utf-8"), re.M)}
            if anchor not in anchors:
                broken.append(f"{target}#{anchor}")
    assert not broken


# ---------- S2 k8s 견본 = 이미지 ----------

def test_s2_k8s_shutdown_and_probe_match_the_image():
    deploy, dockerfile = text(K8S / "gateway.yaml"), text("gateway/Dockerfile")
    grace = int(re.search(r"terminationGracePeriodSeconds: (\d+)", deploy)[1])
    pre_stop = int(re.search(r'command: \["sleep", "(\d+)"\]', deploy)[1])
    drain = int(re.search(r'"--timeout-graceful-shutdown", "(\d+)"', dockerfile)[1])
    assert pre_stop + drain + 5 <= grace                      # 진행 중인 스트림이 끝나고, 끊긴 스트림도 감사 줄을 쓸 여유(5초)
    assert re.search(r"replicas: (\d+)", deploy)[1] == "2" and "minAvailable: 1" in deploy
    probe = re.search(r"readinessProbe:\n\s+httpGet:\n\s+path: (\S+)", deploy)[1]
    assert probe in {getattr(r, "path", None) for r in router.routes}
    mount = re.search(r"mountPath: (\S+)", deploy)[1]
    files = re.search(r"configMapGenerator:\n.*?files:\n\s+- (\S+)", text(K8S / "kustomization.yaml"), re.S)[1]
    assert re.search(r"name: GATEWAY_CONFIG\n\s+value: (\S+)", deploy)[1] == f"{mount}/{files}"
    assert '"--port", "8080"' in dockerfile and "containerPort: 8080" in deploy
