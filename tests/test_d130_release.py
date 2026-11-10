"""D-130(PLAN 20단계): 릴리스 공정 — 워크플로·dependabot·gitleaks 설정의 구조, 버전의 일치, 릴리스 노트 스크립트.

워크플로는 로컬에서 돌릴 수 없다 — 여기서는 파싱·구조·순서만 확인하고, 실제 실행은 첫 태그 푸시가 확인한다(R4).
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
VERSION = "0.2.0"


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def load(rel: str) -> dict:
    return yaml.safe_load(text(rel))


def all_steps(workflow: dict) -> list[dict]:
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


# ---------------------------------------------------------------- R1: 파싱 + SHA 고정
def test_r1_configs_parse_and_every_action_is_pinned_to_a_commit():
    assert [p.name for p in WORKFLOWS] == ["ci.yml", "detect.yml", "release.yml"]
    for path in WORKFLOWS:
        raw = path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(raw)
        assert workflow["permissions"] == {"contents": "read"}, path.name       # 기본은 읽기 — 더 필요한 작업만 작업 단위로 올린다
        lines = [line.strip() for line in raw.splitlines() if re.match(r"\s*(- )?uses:", line)]
        for line in lines:    # 40자 커밋 SHA + 확인 당시의 태그 주석(태그는 옮겨질 수 있다)
            assert re.fullmatch(r"(- )?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), f"{path.name}: {line}"
        parsed = [step["uses"] for step in all_steps(workflow) if "uses" in step]
        assert len(parsed) == len(lines) > 0, path.name                         # 줄로 센 것이 파싱한 것 전부다
    assert load(".github/dependabot.yml")["version"] == 2
    assert tomllib.loads(text(".gitleaks.toml"))["extend"]["useDefault"] is True


def test_r1_run_scripts_take_values_from_the_environment_only():
    """표현식이 셸 코드에 섞이면 태그·브랜치 이름이 명령이 된다 — run 안에는 ${{ }}를 두지 않는다."""
    for path in WORKFLOWS:
        for step in all_steps(yaml.safe_load(path.read_text(encoding="utf-8"))):
            assert "${{" not in step.get("run", ""), f"{path.name}: {step.get('name')}"


# ---------------------------------------------------------------- R2: 릴리스 워크플로의 모양과 순서
def test_r2_release_workflow_gates_then_publishes_then_signs():
    workflow = load(".github/workflows/release.yml")
    assert workflow[True] == {"push": {"tags": ["v*"]}}                          # PyYAML(YAML 1.1)은 키 on을 True로 읽는다
    assert workflow["concurrency"] == {"group": "release", "cancel-in-progress": False, "queue": "max"}
    jobs = workflow["jobs"]
    assert list(jobs) == ["build", "scan", "publish"]
    build, scan, publish = (jobs[name]["steps"] for name in ("build", "scan", "publish"))

    def where(steps: list[dict], key: str, needle: str) -> list[int]:
        return [i for i, step in enumerate(steps) if needle in step.get(key, "")]

    def actions(steps: list[dict]) -> set[str]:
        return {step["uses"].split("@")[0] for step in steps if "uses" in step}

    # --- 권한 경계(리뷰 둘): build에는 서드파티 코드가 없고, 스캐너는 읽기뿐인 scan에서만, 쓰기·OIDC는 publish만
    assert "permissions" not in jobs["build"] and "permissions" not in jobs["scan"]        # 워크플로 기본값(contents: read)
    assert jobs["publish"]["permissions"] == {"contents": "write", "packages": "write", "id-token": "write"}
    assert jobs["scan"]["needs"] == "build" and jobs["publish"]["needs"] == ["build", "scan"]
    assert actions(build) == {"actions/checkout", "actions/upload-artifact"}
    assert actions(scan) == {"actions/download-artifact", "aquasecurity/trivy-action", "anchore/sbom-action", "actions/upload-artifact"}
    assert actions(publish) == {"actions/checkout", "actions/download-artifact", "sigstore/cosign-installer"}
    for steps in (build, scan):
        assert not any(word in str(step) for step in steps for word in ("docker push", "docker login", "cosign", "gh release", "GITHUB_TOKEN", "secrets."))
    for step in build + scan + publish:      # 게이트를 끄는 손잡이가 없다 — 실패하면 거기서 멈춘다
        assert "continue-on-error" not in step and "if" not in step, step.get("name")
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False

    # --- build: 버전 확인 → 빌드 → 파일로(해시는 작업 출력으로) → 넘기기
    (check,) = where(build, "run", 'scripts/release_notes.py -- "$version"')
    (made,) = where(build, "run", "docker build")
    (saved,) = where(build, "run", "docker save")
    (handed,) = where(build, "uses", "actions/upload-artifact@")
    assert [check, made, saved, handed] == sorted([check, made, saved, handed])
    assert "-f gateway/Dockerfile" in build[made]["run"] and "-f detect/Dockerfile" in build[made]["run"]
    local = ["llm-security-gateway:${{ env.VERSION }}", "llm-security-gateway-detect:${{ env.VERSION }}"]
    assert 'docker save -o images.tar "llm-security-gateway:$VERSION" "llm-security-gateway-detect:$VERSION"' in build[saved]["run"]   # 빌드한 둘을 그대로
    assert build[saved]["id"] == "save" and 'sha256=$(sha256sum images.tar' in build[saved]["run"] and '>> "$GITHUB_OUTPUT"' in build[saved]["run"]
    assert jobs["build"]["outputs"] == {"sha256": "${{ steps.save.outputs.sha256 }}"}
    assert build[handed]["with"]["name"] == "images" and build[handed]["with"]["retention-days"] == 7

    # --- scan: 받은 이미지를 올려 목록(막지 않음) → 게이트 → SBOM → 넘기기
    (got,) = where(scan, "uses", "actions/download-artifact@")
    (loaded,) = where(scan, "run", 'docker load -i "$RUNNER_TEMP/images/images.tar"')
    scans = where(scan, "uses", "aquasecurity/trivy-action@")
    sboms = where(scan, "uses", "anchore/sbom-action@")
    (sent,) = where(scan, "uses", "actions/upload-artifact@")
    order = [got, loaded, *scans, *sboms, sent]
    assert order == sorted(order) and len(scans) == 4 and len(sboms) == 2
    assert scan[got]["with"] == {"name": "images", "path": "${{ runner.temp }}/images"}
    listing, gate = [scan[i]["with"] for i in scans[:2]], [scan[i]["with"] for i in scans[2:]]
    assert [c["image-ref"] for c in listing] == [c["image-ref"] for c in gate] == local
    assert all(c["cache"] == "false" for c in listing + gate)                   # Actions 캐시의 바이너리·DB를 쓰지 않는다
    for cfg in listing:      # 수정판이 없는 것까지 표로 — 막지 않는다(문서가 '로그의 표로 본다'고 한 것)
        assert (cfg["severity"], cfg["exit-code"]) == ("HIGH,CRITICAL", "0") and "ignore-unfixed" not in cfg
    for cfg in gate:         # 고칠 수 있는 HIGH·CRITICAL이 있으면 여기서 멈춘다 — publish가 돌지 않는다
        assert (cfg["severity"], cfg["exit-code"], cfg["ignore-unfixed"]) == ("HIGH,CRITICAL", "1", True)
    for i, image in zip(sboms, local):
        cfg = scan[i]["with"]
        assert (cfg["image"], cfg["format"], cfg["upload-release-assets"]) == (image, "spdx-json", False)
        assert cfg["output-file"] in scan[sent]["with"]["path"]
    assert scan[sent]["with"]["name"] == "sboms"

    # --- publish: 받은 파일은 작업 폴더 밖에 → 해시 확인 → 버전 태그 푸시 → 서명·증명 → latest → 릴리스
    downloads = where(publish, "uses", "actions/download-artifact@")
    assert [publish[i]["with"] for i in downloads] == [{"name": "images", "path": "${{ runner.temp }}/release/images"}, {"name": "sboms", "path": "${{ runner.temp }}/release/sboms"}]
    (pushed,) = where(publish, "run", "docker load -i")
    (sign,) = where(publish, "run", "cosign sign")
    (latest,) = where(publish, "run", ":latest")
    (release,) = where(publish, "run", "gh release create")
    order = [*downloads, pushed, where(publish, "uses", "sigstore/cosign-installer@")[0], sign, latest, release]
    assert order == sorted(order) and len([s for s in publish if "run" in s]) == 4      # run 단계는 이 넷뿐이다
    push_run = publish[pushed]["run"]
    assert publish[pushed]["env"]["IMAGES_SHA256"] == "${{ needs.build.outputs.sha256 }}"
    verify = 'echo "$IMAGES_SHA256  $RUNNER_TEMP/release/images/images.tar" | sha256sum -c -'
    assert verify in push_run and push_run.index(verify) < push_run.index("docker load") < push_run.index("docker login")   # build의 그 파일인지 본 뒤에만
    runs = "\n".join(step.get("run", "") for step in publish)
    assert "docker build" not in runs                                              # 다시 빌드하지 않는다
    for name in ("images.tar", "llm-security-gateway.spdx.json", "llm-security-gateway-detect.spdx.json"):   # 받은 파일은 늘 작업 폴더 밖의 경로로
        assert runs.count(name) == runs.count(f"/{name}") > 0 and all(part.rstrip('"').endswith(("/release/images", "/release/sboms")) for part in runs.split(f"/{name}")[:-1])
    assert ":latest" not in push_run and "docker push" in push_run                 # latest는 서명 뒤에만
    signing = publish[sign]["run"].splitlines()
    assert [line.split()[:2] for line in signing] == [["cosign", "sign"]] * 2 + [["cosign", "attest"]] * 2
    assert [line.split()[-1] for line in signing] == ['"$GATEWAY_REF"', '"$DETECT_REF"'] * 2            # 태그가 아니라 다이제스트
    assert all("--type spdxjson --predicate" in line for line in signing[2:])
    assert "--verify-tag" in publish[release]["run"] and '-- "$VERSION"' in publish[release]["run"]

    # 올리는 이름이 k8s 견본이 받는 이름이다
    images = re.findall(r"image: (ghcr\.io/hongjinkong/(\S+):(\S+))", text("deploy/k8s/gateway.yaml"))
    assert [(name, tag) for _, name, tag in images] == [("llm-security-gateway", VERSION), ("llm-security-gateway-detect", VERSION)]
    for _, name, _ in images:
        assert re.search(rf"^push \w+_REF {name}$", push_run, re.M)
    assert 'ghcr.io/$owner/$2:$version' in push_run


def test_r2_ci_scans_pushed_commits_for_secrets():
    job = load(".github/workflows/ci.yml")["jobs"]["secrets"]
    assert job["if"] == "github.event_name != 'workflow_dispatch'"               # 손으로 돌리면 전체 히스토리를 훑는다(D-130 §3)
    checkout, gitleaks = job["steps"]
    assert checkout["with"]["fetch-depth"] == 0 and gitleaks["uses"].startswith("gitleaks/gitleaks-action@")
    assert gitleaks["env"]["GITLEAKS_VERSION"] == re.search(r"gitleaks (\d+\.\d+\.\d+)", text(".gitleaks.toml"))[1]   # 설정을 맞춘 버전


# ---------------------------------------------------------------- R3: 버전·dependabot·gitleaks 허용 목록·릴리스 노트
def test_r3_version_is_the_same_everywhere():
    from gateway.version import VERSION as installed    # 설치(pip install -e .)한 환경이 전제다 — 버전을 올리면 다시 설치한다
    project = tomllib.loads(text("pyproject.toml"))["project"]["version"]
    first = re.search(r"^## (.+)$", text("CHANGELOG.md"), re.M)[1]
    assert project == installed == VERSION
    assert re.fullmatch(rf"{re.escape(VERSION)} — \d{{4}}-\d{{2}}-\d{{2}}", first)   # '미출시' 절을 위에 두지 않는다 — 릴리스가 이 절을 읽는다


def test_r3_dependabot_watches_pip_actions_and_docker():
    updates = load(".github/dependabot.yml")["updates"]
    got = {u["package-ecosystem"]: set(u.get("directories") or [u["directory"]]) for u in updates}
    assert got == {"pip": {"/", "/detect"}, "github-actions": {"/"}, "docker": {"/gateway", "/detect"}}
    assert all(u["schedule"]["interval"] == "weekly" for u in updates)
    for rel in ("pyproject.toml", "detect/requirements.txt", "gateway/Dockerfile", "detect/Dockerfile"):   # 가리키는 폴더에 볼 파일이 있다
        assert (ROOT / rel).is_file(), rel


def test_r3_gitleaks_allows_synthetic_key_paths_and_nothing_else():
    cfg = tomllib.loads(text(".gitleaks.toml"))

    def allowed(rel: str) -> bool:
        return any(re.search(pattern, rel) for pattern in cfg["allowlist"]["paths"])

    # 합성 키가 실제로 있다 — 허용 목록이 없으면 기본 규칙에 걸린다
    assert len(re.findall(r"sk-ant-|ghp_|AKIA[0-9A-Z]{16}|-----BEGIN|AIza", text("eval/pii/corpus.jsonl"))) > 0
    for rel in ("eval/pii/corpus.jsonl", "eval/pii/hard.jsonl", "eval/injection/train/train.jsonl", "tests/test_pii.py"):
        assert allowed(rel), rel
    for rel in ("gateway/main.py", "gateway/data/x.jsonl", "detect/app.py", "detect/models.json", "detect/tests/test_detect.py", "scripts/release_notes.py",
                "deploy/compose.yml", "deploy/k8s/secret.env.example", "docs/operations.md", "README.md", ".github/workflows/release.yml", "web/tests/x.py"):
        assert not allowed(rel), rel                                             # 제품 코드·설정·문서·배포 견본은 검사한다
    (rule,) = cfg["rules"]
    (hashes,) = rule["allowlists"]
    assert (rule["id"], hashes["condition"]) == ("generic-api-key", "AND")      # 경로와 값의 꼴이 둘 다 맞을 때만 뺀다
    assert re.search(hashes["paths"][0], "detect/models.json") and not re.search(hashes["paths"][0], "x/detect/models.json")
    assert re.search(hashes["regexes"][0], "0f" * 32) and not re.search(hashes["regexes"][0], "sk-" + "0f" * 32)


def test_r3_detect_image_carries_the_licenses_of_the_models_it_embeds():
    """공개로 올리는 사이드카 이미지는 모델 가중치를 담는다 — 내장하는 모델마다 출처·리비전·라이선스 고지가 이미지에 있다(리뷰)."""
    import json
    docker = text("detect/Dockerfile")
    models = json.loads(text("detect/models.json"))
    notices = text("detect/THIRD_PARTY_NOTICES.md")
    assert re.search(r"^COPY LICENSE detect/THIRD_PARTY_NOTICES\.md /licenses/$", docker, re.M)
    embedded = re.findall(r"^ARG (?:MODEL|INJECTION_MODEL)=(\S+)$", docker, re.M)
    assert len(embedded) == 2
    for name in embedded:
        spec = models[name]
        row = next(line for line in notices.splitlines() if line.startswith(f"| `{name}`"))
        assert spec["id"] in row and spec["revision"] in row and spec["license"] in row, name
        if "Horizon-Labs" in spec["id"]:                 # 제작자가 LICENSE·NOTICE를 둔 저장소 — fetch가 모델 폴더에 함께 받는다
            assert {"LICENSE", "NOTICE"} <= set(spec["files"]), name


def _notes(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/release_notes.py", *args], cwd=ROOT, capture_output=True, text=True)


def test_r3_release_notes_checks_the_version_and_prints_the_section():
    plain = _notes(VERSION)
    assert plain.returncode == 0 and "D-130" in plain.stdout
    assert "\n## " not in plain.stdout and not plain.stdout.startswith("## ")     # 이 버전의 절만, 제목 줄 없이
    assert len(plain.stdout) < 100_000                                           # GitHub 릴리스 본문 상한(125,000자) 안
    wrong = _notes("9.9.9")
    assert wrong.returncode == 1 and "pyproject.toml" in wrong.stderr and wrong.stdout == ""
    for odd in ("-h", "--help"):        # 태그 v-h — 워크플로는 `--` 뒤에 넘긴다. 도움말을 찍고 0으로 끝나면 버전 확인을 지나친다(리뷰)
        helped = _notes("--", odd)
        assert helped.returncode == 1 and "pyproject.toml" in helped.stderr and helped.stdout == ""

    refs = ["ghcr.io/o/llm-security-gateway@sha256:" + "0a" * 32, "ghcr.io/o/llm-security-gateway-detect@sha256:" + "0b" * 32]
    full = _notes(VERSION, "--repo", "o/r", "--image", refs[0], "--image", refs[1])
    identity = f"--certificate-identity https://github.com/o/r/.github/workflows/release.yml@refs/tags/v{VERSION} --certificate-oidc-issuer https://token.actions.githubusercontent.com"
    for ref in refs:    # 검증 명령이 그 저장소·그 워크플로·그 태그의 서명만 받는다
        assert f"cosign verify {identity} {ref}\n" in full.stdout
        assert f"cosign verify-attestation --type spdxjson {identity} {ref}\n" in full.stdout
    assert full.stdout.startswith(plain.stdout.rstrip("\n"))


def test_r3_release_notes_refuses_a_version_without_a_changelog_section(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts" / "release_notes.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    for changelog in ("# 변경 기록\n\n## 미출시\n\n- 무엇\n\n## 1.2.2 — 2026-01-01\n\n- 옛것\n",     # 절이 없다
                      "# 변경 기록\n\n## 1.2.3 — 2026-01-02\n\n## 1.2.2 — 2026-01-01\n\n- 옛것\n",      # 절이 비었다
                      "# 변경 기록\n\n## 1.2.30 — 2026-01-02\n\n- 다른 버전\n"):                          # 앞부분만 같은 버전
        (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        with pytest.raises(SystemExit, match="CHANGELOG"):
            mod.notes("1.2.3")
    (tmp_path / "CHANGELOG.md").write_text("# 변경 기록\n\n## 1.2.3 — 2026-01-02\n\n- 새것\n\n## 1.2.2 — 2026-01-01\n\n- 옛것\n", encoding="utf-8")
    assert mod.notes("1.2.3") == "- 새것\n"


def test_s1_images_share_a_pinned_base_and_apply_debian_security_updates():
    """D-135: 첫 릴리스가 베이스 빌드 뒤에 나온 Debian 보안 갱신(apt·zlib)으로 스캔 게이트에서 멈췄다 — 세 이미지는 같은 고정 베이스 위에서
    비root로 바꾸기 전에 갱신을 적용하고 패키지 목록을 같은 층에서 지운다."""
    bases = set()
    for rel in ("gateway/Dockerfile", "detect/Dockerfile", "web/Dockerfile"):
        docker = text(rel)
        bases.add(re.search(r"^FROM (\S+)$", docker, re.M)[1])
        upgrade = re.search(r"^RUN apt-get update \\\n && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \\\n && rm -rf /var/lib/apt/lists/\*$", docker, re.M)
        assert upgrade, rel
        assert docker.index("FROM ") < upgrade.start() < docker.index("\nUSER 10001"), rel
    (base,) = bases
    assert re.fullmatch(r"python:3\.12-slim@sha256:[0-9a-f]{64}", base)
