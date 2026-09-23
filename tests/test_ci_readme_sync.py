"""D-069: CI 워크플로가 README 6절의 설치 절차를 **그대로** 실행하는지 검사한다.

**이 파일은 `.github/workflows/cpu-tests.yml`보다 먼저 쓰였다.**

왜 필요한가. CI는 초록불을 만들기 위해 README와 다른 길로 가기 쉽다. 예를 들어
워크플로에만 `pip install numpy`를 한 줄 넣으면 CI는 통과하지만, README대로 설치한
사람은 여전히 실패한다(D-066 5절이 실제로 그 상태였다). 그러면 CI의 초록불은
README에 대한 증거가 아니다.

정답의 출처는 README다. 이 테스트는 README 6절에서 명령을 읽어 오고, 워크플로가
그 명령을 같은 순서로 실행하며 그 밖에 환경을 바꾸는 일을 하지 않는지 본다.
워크플로의 모양을 베껴 적은 기대값은 두지 않는다.

허용하는 차이는 셋뿐이다.
  - `git clone`·`cd` → `actions/checkout` (새 체크아웃)
  - 스텝마다 셸이 새로 뜨므로 이후 스텝 앞의 `source .venv/bin/activate`
  - 환경을 바꾸지 않는 읽기 전용 검사: `pip check`, `pip freeze`, junit 판정
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "cpu-tests.yml"

VERIFY_ONLY = {"pip check", "pip freeze > pip-freeze.txt",
               "python3 scripts/ci_junit_check.py junit.xml"}
ALLOWED_ADDOPTS = {"--junitxml=junit.xml", "-rs", "-ra"}
ALLOWED_USES = {
    "actions/checkout": {"persist-credentials"},
    "actions/setup-python": {"python-version"},
    "actions/upload-artifact": None,
}
CORE_STEP_KEYS = {"install": {"id", "name", "run"}, "test": {"id", "name", "run", "env"}}
# D-071: 판정 근거를 만드는 스텝. 없거나 건너뛰어지면 CI가 초록이어도 A2·A4는 판정된 적이 없다.
VERIFY_STEP_KEYS = {"pip-check": {"id", "name", "run"}, "junit": {"id", "name", "run", "if"}}
EVIDENCE_FILES = {"junit.xml", "pip-freeze.txt"}
RUNNER = "ubuntu-24.04"
# 앞 스텝이 실패해도 도는 조건. `${{ }}` 없이 쓴 형태도 GitHub은 같은 식으로 읽는다.
RUNS_AFTER_FAILURE = re.compile(r"(?:\$\{\{\s*)?(?:!\s*cancelled\(\)|always\(\))(?:\s*\}\})?")


# ------------------------------------------------------------ README 6절 읽기

def section6(text: str) -> str:
    m = re.search(r"^## 6\..*?$(.*?)(?=^## )", text, re.M | re.S)
    assert m, "README에서 '## 6.' 절을 찾지 못했다 — 절 번호가 바뀌었으면 이 테스트와 D-069를 함께 본다"
    return m.group(1)


def shell_blocks(section: str) -> list[list[str]]:
    blocks = re.findall(r"^```(?:bash|sh)[ \t]*\n(.*?)^```", section, re.M | re.S)
    return [[ln.strip() for ln in b.splitlines()
             if ln.strip() and not ln.strip().startswith("#")] for b in blocks]


def readme_steps(text: str) -> tuple[list[str], list[str]]:
    """(설치 명령, 테스트 명령). 테스트 블록은 `pytest`로 시작하는 줄이 있는 첫 블록이다.
    그 앞의 블록들이 설치이고, 그 뒤(uvicorn·curl)는 수동 데모라 CI 대상이 아니다."""
    blocks = shell_blocks(section6(text))
    idx = next((i for i, b in enumerate(blocks)
                if any(ln.split()[0] == "pytest" for ln in b)), None)
    assert idx is not None, "README 6절에 pytest 명령이 없다"
    install = [ln for b in blocks[:idx] for ln in b]
    assert len(install) >= 2 and install[0].startswith("git clone ") and install[1].startswith("cd "), (
        "README 6절 설치가 `git clone`·`cd`로 시작하지 않는다 — checkout 대응을 다시 확인한다")
    return install[2:], blocks[idx]


def activate_line(install: list[str]) -> str:
    acts = [ln for ln in install if ln.startswith("source ") and ln.endswith("/bin/activate")]
    assert len(acts) == 1, f"README 설치 절차의 activate 줄이 정확히 하나가 아니다: {acts}"
    return acts[0]


def readme_min_python(text: str) -> str:
    m = re.search(r"Python\s+(3\.\d+)\s*이상", section6(text))
    assert m, "README 6절에 'Python 3.x 이상' 요건이 없다 — numpy·scipy는 3.12 이상을 요구한다(D-069 1절)"
    return m.group(1)


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


# ------------------------------------------------------------ 워크플로 읽기

@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), f"워크플로가 없다: {WORKFLOW.relative_to(ROOT)}"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(workflow) -> dict:
    jobs = workflow.get("jobs") or {}
    assert len(jobs) == 1, f"잡은 하나여야 한다 — 어느 잡이 README를 검사하는지 모호해진다: {list(jobs)}"
    return next(iter(jobs.values()))


@pytest.fixture(scope="module")
def steps(job) -> list[dict]:
    return job.get("steps") or []


def run_lines(step: dict) -> list[str]:
    return [ln.strip() for ln in str(step.get("run", "")).splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def step_by_id(steps: list[dict], sid: str) -> tuple[int, dict]:
    found = [(i, s) for i, s in enumerate(steps) if s.get("id") == sid]
    assert len(found) == 1, f"id={sid!r} 스텝이 정확히 하나가 아니다 ({len(found)}개)"
    return found[0]


# ------------------------------------------------------------ 1. 설치·테스트 명령이 README와 같다

def test_install_step_runs_readme_install_commands_verbatim(readme, steps):
    install, _ = readme_steps(readme)
    _, step = step_by_id(steps, "install")
    assert run_lines(step) == install


def test_test_step_runs_readme_test_command_after_reactivating(readme, steps):
    install, test = readme_steps(readme)
    _, step = step_by_id(steps, "test")
    assert run_lines(step) == [activate_line(install), *test]


def test_install_runs_before_test(steps):
    i, _ = step_by_id(steps, "install")
    t, _ = step_by_id(steps, "test")
    assert i < t


def test_core_steps_have_no_condition_directory_shell_or_failure_override(steps):
    """`if:`는 스텝을 건너뛸 수 있고, `continue-on-error`는 실패를 삼키고,
    `working-directory`·`shell`은 README와 다른 곳·다른 셸에서 돌게 만든다."""
    for sid, allowed in CORE_STEP_KEYS.items():
        _, step = step_by_id(steps, sid)
        assert set(step) <= allowed, f"{sid} 스텝에 허용되지 않은 키: {sorted(set(step) - allowed)}"


# ------------------------------------------------------------ 2. 그 밖의 스텝은 환경을 바꾸지 않는다

def test_other_run_steps_are_read_only_checks(readme, steps):
    install, _ = readme_steps(readme)
    allowed = VERIFY_ONLY | {activate_line(install)}
    for s in steps:
        if "run" in s and s.get("id") not in CORE_STEP_KEYS:
            extra = [ln for ln in run_lines(s) if ln not in allowed]
            assert not extra, f"README에 없는 명령이 CI에 있다 (스텝 {s.get('id') or s.get('name')}): {extra}"


def test_only_known_actions_with_known_inputs(steps):
    """setup-python의 `cache`·`pip-install` 같은 입력은 README에 없는 설치 경로다.
    checkout의 `ref`·`repository`는 판정 대상과 다른 코드를 받게 한다(D-069 V1)."""
    for s in steps:
        if "uses" not in s:
            continue
        name = s["uses"].split("@")[0]
        assert name in ALLOWED_USES, f"허용되지 않은 액션: {s['uses']}"
        allowed = ALLOWED_USES[name]
        if allowed is not None:
            extra = set(s.get("with") or {}) - allowed
            assert not extra, f"{name}에 허용되지 않은 입력: {sorted(extra)}"


def test_no_failure_swallowing_anywhere(workflow, job, steps):
    assert "continue-on-error" not in job
    for s in steps:
        assert "continue-on-error" not in s, f"스텝 {s.get('id') or s.get('name')}가 실패를 삼킨다"


def test_environment_is_not_changed_outside_pytest_reporting(workflow, job, steps):
    """PIP_INDEX_URL·PIP_CONSTRAINT 같은 환경변수는 README에 없는 설치 경로다.
    PYTEST_ADDOPTS에 `-k`·`--ignore`·`--deselect`가 들어가면 테스트가 조용히 빠진다."""
    assert "env" not in workflow, "워크플로 수준 env 금지"
    assert "env" not in job, "잡 수준 env 금지"
    for s in steps:
        if "env" in s:
            assert s.get("id") == "test", f"test 외 스텝의 env 금지: {s.get('id') or s.get('name')}"
    _, test = step_by_id(steps, "test")
    env = test.get("env") or {}
    assert set(env) <= {"PYTEST_ADDOPTS"}, f"test 스텝 env: {sorted(env)}"
    tokens = shlex.split(str(env.get("PYTEST_ADDOPTS", "")))
    assert "--junitxml=junit.xml" in tokens, "junit 판정기가 읽을 파일이 지정되지 않았다"
    assert set(tokens) <= ALLOWED_ADDOPTS, f"보고 외 pytest 옵션: {sorted(set(tokens) - ALLOWED_ADDOPTS)}"


# ------------------------------------------------------------ 3. Python 버전은 README의 요건을 따른다

def test_matrix_covers_readme_minimum_python(readme, job):
    versions = (job.get("strategy") or {}).get("matrix", {}).get("python")
    assert isinstance(versions, list) and versions, "matrix.python 목록이 없다"
    assert all(isinstance(v, str) for v in versions), (
        f"버전은 따옴표로 감싼 문자열이어야 한다 — YAML은 3.10을 3.1로 읽는다: {versions!r}")
    minimum = readme_min_python(readme)
    assert minimum in versions, f"README 하한 {minimum}이 CI에 없다: {versions}"
    assert all(version_key(v) >= version_key(minimum) for v in versions), (
        f"README 하한보다 낮은 버전은 README대로 설치되지 않는다: {versions}")


def test_setup_python_uses_the_matrix_value(steps):
    """버전을 직접 적으면 matrix는 장식이 되고 모든 칸이 같은 버전으로 돈다."""
    setups = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python@")]
    assert len(setups) == 1, f"setup-python은 정확히 하나: {len(setups)}"
    value = str((setups[0].get("with") or {}).get("python-version", ""))
    assert re.fullmatch(r"\$\{\{\s*matrix\.python\s*\}\}", value), f"python-version={value!r}"


def test_one_version_failing_does_not_cancel_the_other(job):
    """D-069 6절: '한 버전에서만 실패'를 분류하려면 다른 버전 결과가 남아야 한다."""
    assert (job.get("strategy") or {}).get("fail-fast") is False


# ------------------------------------------------------------ 4. 판정 근거를 만드는 스텝이 반드시 있다 (D-071)
# 1~3절은 "README에 없는 일을 하면" 잡는다. 이 절은 "해야 할 일을 빼면" 잡는다.
# 예: junit 스텝을 지우면 skip이 있어도 CI는 초록이 되고, 그 초록은 A4의 증거가 아니다.

def test_pip_check_step_records_the_installed_environment(readme, steps):
    """A2(`pip check`)와 실패 분류의 근거(`pip freeze`, D-069 6절 ModuleNotFoundError 행)가 이 스텝에서 나온다.
    freeze가 check보다 먼저다. run 스텝은 `bash -e`로 돌아 `pip check`가 실패하면 그 뒤 줄은 실행되지
    않는다 — 의존성 충돌을 분류해야 하는 바로 그 실행에서 freeze가 사라진다."""
    install, _ = readme_steps(readme)
    i, _ = step_by_id(steps, "install")
    p, step = step_by_id(steps, "pip-check")
    assert i < p, "pip-check는 설치된 환경을 봐야 하므로 install 뒤에 있어야 한다"
    assert run_lines(step) == [activate_line(install), "pip freeze > pip-freeze.txt", "pip check"]


def test_junit_verdict_runs_after_tests_even_when_they_fail(steps):
    """테스트가 실패한 실행에서도 실패·skip·테스트 수를 판정해야 분류(D-069 6절)가 가능하다.
    기본 조건(success())이면 테스트 실패 시 이 스텝이 건너뛰어져 junit 판정이 사라진다."""
    t, _ = step_by_id(steps, "test")
    j, step = step_by_id(steps, "junit")
    assert t < j, "junit 판정은 junit.xml을 만드는 test 스텝 뒤에 있어야 한다"
    assert run_lines(step) == ["python3 scripts/ci_junit_check.py junit.xml"]
    cond = str(step.get("if", "")).strip()
    assert RUNS_AFTER_FAILURE.fullmatch(cond), f"test 실패 후에도 돌아야 한다: if={cond!r}"


def test_evidence_is_uploaded_even_when_tests_fail(steps):
    """D-069-1 기록과 실패 분류는 junit.xml·pip-freeze.txt를 근거로 한다. 로그만으로는 조용한 누락을 못 본다."""
    ups = [(i, s) for i, s in enumerate(steps)
           if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(ups) == 1, f"upload-artifact는 정확히 하나: {len(ups)}"
    u, step = ups[0]
    t, _ = step_by_id(steps, "test")
    p, _ = step_by_id(steps, "pip-check")
    assert u > max(t, p), "근거 파일이 만들어진 뒤에 올려야 한다"
    cond = str(step.get("if", "")).strip()
    assert RUNS_AFTER_FAILURE.fullmatch(cond), f"실패한 실행의 근거도 남아야 한다: if={cond!r}"
    paths = {ln.strip() for ln in str((step.get("with") or {}).get("path", "")).splitlines() if ln.strip()}
    assert EVIDENCE_FILES <= paths, f"올리지 않는 근거 파일: {sorted(EVIDENCE_FILES - paths)}"


def test_verify_steps_have_no_directory_shell_or_failure_override(steps):
    """`working-directory`는 다른 junit.xml을 읽게 만들고, `shell`은 README와 다른 셸에서 돌게 만든다."""
    for sid, allowed in VERIFY_STEP_KEYS.items():
        _, step = step_by_id(steps, sid)
        assert set(step) <= allowed, f"{sid} 스텝에 허용되지 않은 키: {sorted(set(step) - allowed)}"


def test_no_default_directory_shell_or_other_image(workflow, job):
    """`defaults.run`은 모든 run 스텝의 디렉터리·셸을 한 줄로 바꾼다(스텝 단위 검사를 우회).
    `container`·`services`는 러너 대신 다른 이미지에서 돌게 해 사전 설치가 섞일 수 있다(D-069 V2)."""
    assert "defaults" not in workflow, "워크플로 수준 defaults 금지"
    for key in ("defaults", "container", "services"):
        assert key not in job, f"잡 수준 {key} 금지"


def test_runner_is_the_one_d069_describes(job):
    """D-069 7절의 '증명하지 않는 것'은 Ubuntu 24.04를 전제로 쓰였다. `ubuntu-latest`는 예고 없이 바뀐다."""
    assert job.get("runs-on") == RUNNER, f"runs-on={job.get('runs-on')!r}"
