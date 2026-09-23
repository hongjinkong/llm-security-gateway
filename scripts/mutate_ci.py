#!/usr/bin/env python3
"""D-069 변이 검사 — CI 판정 도구의 테스트가 실제 문제를 잡는지 확인한다.

`scripts/mutate_audit_vault.py`와 같은 방식이다. **임시 복사본만 바꾼다.**
원본은 건드리지 않으므로 중간에 죽어도 되돌릴 것이 없다.

두 종류를 함께 넣는다(D-067 4절).
  - 결함 복원: 막으려던 문제를 되살린다 → 지정한 테스트가 실패해야 한다
  - 과잉 수정·부작용: 정상인 것까지 막거나 보고 숫자를 오염시킨다 → 역시 실패해야 한다
    결함 복원만으로는 "고쳤다"와 "기능을 죽였다"를 구분하지 못한다.
  - 무해 변경(D-071): 계약과 무관한 변경(스텝 이름, README 데모 블록, 빈 줄 등) → **통과해야 한다.**
    테스트가 너무 빡빡하면 README 문장 하나 고칠 때마다 CI가 깨지고, 그러면 사람들은 테스트를 끈다.

검출의 조건: 지정한 테스트가 **전부** 실패했고, 실패가 assert 실패이며, 수집·설정 오류가
없다. 변이가 문법을 깨서 "실패"가 나온 것은 검출로 세지 않는다(.py는 compile, .yml은 YAML 파싱으로 막는다).
무해 변경의 조건: 종료 0, 실패·오류·skip 0, 테스트 수가 기준선과 같다.

사용: python3 scripts/mutate_ci.py
측정이 아니다. docker·Ollama·GPU·네트워크를 쓰지 않는다.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]

J = "scripts/ci_junit_check.py"
JT = "tests/test_ci_junit_check.py"
W = ".github/workflows/cpu-tests.yml"
R = "README.md"
ST = "tests/test_ci_readme_sync.py"
PASS_KINDS = {"무해 변경"}

INVALID_TESTS = [
    "test_missing_file_is_invalid", "test_truncated_file_is_invalid",
    "test_empty_file_is_invalid", "test_non_junit_root_is_invalid",
    "test_summary_hiding_a_skip_is_invalid",
    "test_summary_count_not_matching_testcases_is_invalid",
    "test_missing_summary_attribute_is_invalid",
]

# (id, 종류, 설명, 대상 파일, 테스트 파일, [(앵커, 바꿀 것)], 실패해야 하는 테스트)
MUTATIONS = [
    ("J1", "결함 복원", "skip·xfail을 문제로 세지 않는다", J, JT,
     [('for a in ("failures", "errors", "skipped") if total[a]',
       'for a in ("failures", "errors") if total[a]')],
     ["test_skip_is_rejected", "test_xfail_is_rejected"]),
    ("J2", "결함 복원", "테스트 0개를 합격시킨다", J, JT,
     [('    if total["tests"] == 0:', '    if False:')],
     ["test_zero_tests_is_invalid"]),
    ("J3", "결함 복원", "요약 속성만 믿고 개별 결과와 대조하지 않는다", J, JT,
     [("            if d != o:", "            if False:"),
      ("                total[a] += o[a]", "                total[a] += d[a]")],
     ["test_summary_hiding_a_skip_is_invalid",
      "test_summary_count_not_matching_testcases_is_invalid"]),
    ("J4", "결함 복원", "무효(2)를 불합격(1)으로 뭉갠다 — 세 갈래 계약 붕괴", J, JT,
     [("        return 2, None, [str(e)]", "        return 1, None, [str(e)]")],
     INVALID_TESTS),
    ("J5", "결함 복원", "요약 속성이 없으면 0으로 간주한다", J, JT,
     [('            raise Invalid(f"<testsuite>에 {a} 속성이 없다")', '            v = "0"')],
     ["test_missing_summary_attribute_is_invalid"]),
    ("O1", "과잉 수정", "testcase의 자식 요소를 전부 오류로 센다(system-out·properties 포함)", J, JT,
     [('        "errors": sum(len(c.findall("error")) for c in cases),',
       '        "errors": sum(len(list(c)) for c in cases),')],
     ["test_captured_output_and_properties_do_not_count_as_problems"]),
    ("O2", "과잉 수정", "<testsuites> 감싸개가 없는 뿌리를 거부한다", J, JT,
     [('    if root.tag == "testsuite":\n        return [root]',
       '    if False:\n        return [root]')],
     ["test_bare_testsuite_root_is_accepted"]),
    ("O3", "과잉 수정", "테스트 0개를 무효(2)가 아니라 불합격(1)으로 판정한다", J, JT,
     [('        return 2, total, ["테스트가 0개다', '        return 1, total, ["테스트가 0개다')],
     ["test_zero_tests_is_invalid"]),
    ("O4", "부작용", "요약 줄의 passed에 문제 테스트까지 넣는다 — A5 보고 숫자 오염", J, JT,
     [('    total["passed"] = total["tests"] - len(_problem_cases(suites))',
       '    total["passed"] = total["tests"]')],
     ["test_skip_is_rejected", "test_xfail_is_rejected",
      "test_failure_is_rejected", "test_fixture_error_is_rejected"]),

    # ---- README 동기화 (D-069 3절 1, D-071). 잡혀야 하는 것: README와 다른 설치·환경·실패 무시
    ("S1", "결함 복원", "워크플로에만 pip install numpy (D-066 5절 상태의 재현)", W, ST,
     [("          pip install -r requirements.txt\n",
       "          pip install -r requirements.txt\n          pip install numpy\n")],
     ["test_install_step_runs_readme_install_commands_verbatim"]),
    ("S2", "결함 복원", "README만 requirements 파일명을 바꾼다", R, ST,
     [("source .venv/bin/activate\npip install -r requirements.txt\n```",
       "source .venv/bin/activate\npip install -r requirements-gateway.txt\n```")],
     ["test_install_step_runs_readme_install_commands_verbatim"]),
    ("S3", "결함 복원", "PYTEST_ADDOPTS에 -k — 테스트가 조용히 빠진다", W, ST,
     [('PYTEST_ADDOPTS: "--junitxml=junit.xml -rs"',
       'PYTEST_ADDOPTS: "--junitxml=junit.xml -rs -k \'not slow\'"')],
     ["test_environment_is_not_changed_outside_pytest_reporting"]),
    ("S4", "결함 복원", "setup-python cache: pip — README에 없는 설치 경로(V2)", W, ST,
     [("          python-version: ${{ matrix.python }}\n",
       "          python-version: ${{ matrix.python }}\n          cache: pip\n")],
     ["test_only_known_actions_with_known_inputs"]),
    ("S5", "결함 복원", "matrix에서 README 하한 3.12 제거", W, ST,
     [('python: ["3.12", "3.14"]', 'python: ["3.14"]')],
     ["test_matrix_covers_readme_minimum_python"]),
    ("S6", "결함 복원", "matrix 따옴표 제거 — YAML이 숫자로 읽는다", W, ST,
     [('python: ["3.12", "3.14"]', "python: [3.12, 3.14]")],
     ["test_matrix_covers_readme_minimum_python"]),
    ("S7", "결함 복원", "test 스텝 continue-on-error — 실패를 삼킨다", W, ST,
     [("      - id: test\n", "      - id: test\n        continue-on-error: true\n")],
     ["test_no_failure_swallowing_anywhere",
      "test_core_steps_have_no_condition_directory_shell_or_failure_override"]),
    ("S8", "결함 복원", "python-version 직접 기입 — matrix가 장식이 된다", W, ST,
     [("python-version: ${{ matrix.python }}", 'python-version: "3.12"')],
     ["test_setup_python_uses_the_matrix_value"]),
    ("S9", "결함 복원", "test 스텝 activate 삭제 — venv 밖 pytest", W, ST,
     [("          source .venv/bin/activate\n          pytest -q\n", "          pytest -q\n")],
     ["test_test_step_runs_readme_test_command_after_reactivating"]),
    ("S10", "결함 복원", "junit 판정 스텝 삭제 — A4 없는 초록 (D-071)", W, ST,
     [("      - id: junit\n        name: junit 판정 (D-069 A4)\n        if: ${{ !cancelled() }}\n"
       "        run: python3 scripts/ci_junit_check.py junit.xml\n\n", "")],
     ["test_junit_verdict_runs_after_tests_even_when_they_fail",
      "test_verify_steps_have_no_directory_shell_or_failure_override"]),
    ("S11", "결함 복원", "junit 스텝 if 제거 — 테스트 실패 시 판정이 건너뛰어진다 (D-071)", W, ST,
     [("        name: junit 판정 (D-069 A4)\n        if: ${{ !cancelled() }}\n",
       "        name: junit 판정 (D-069 A4)\n")],
     ["test_junit_verdict_runs_after_tests_even_when_they_fail"]),
    ("S12", "결함 복원", "pip-check 스텝 삭제 — A2 미판정 (D-071)", W, ST,
     [("      - id: pip-check\n        name: pip freeze · pip check (D-069 A2)\n        run: |\n"
       "          source .venv/bin/activate\n          pip freeze > pip-freeze.txt\n          pip check\n\n", "")],
     ["test_pip_check_step_records_the_installed_environment",
      "test_verify_steps_have_no_directory_shell_or_failure_override",
      "test_evidence_is_uploaded_even_when_tests_fail"]),
    ("S13", "결함 복원", "pip check를 freeze보다 먼저 — 충돌 시 freeze가 사라진다 (D-071)", W, ST,
     [("          pip freeze > pip-freeze.txt\n          pip check\n",
       "          pip check\n          pip freeze > pip-freeze.txt\n")],
     ["test_pip_check_step_records_the_installed_environment"]),
    ("S14", "결함 복원", "근거 파일 업로드 삭제 (D-071)", W, ST,
     [("\n      - name: 근거 파일 업로드\n        if: ${{ !cancelled() }}\n"
       "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1, node24\n"
       "        with:\n          name: ci-evidence-py${{ matrix.python }}\n          path: |\n"
       "            junit.xml\n            pip-freeze.txt\n", "\n")],
     ["test_evidence_is_uploaded_even_when_tests_fail"]),
    ("S15", "결함 복원", "업로드에서 pip-freeze.txt 누락 (D-071)", W, ST,
     [("            junit.xml\n            pip-freeze.txt\n", "            junit.xml\n")],
     ["test_evidence_is_uploaded_even_when_tests_fail"]),
    ("S16", "결함 복원", "업로드 if 제거 — 실패한 실행의 근거가 안 남는다 (D-071)", W, ST,
     [("      - name: 근거 파일 업로드\n        if: ${{ !cancelled() }}\n", "      - name: 근거 파일 업로드\n")],
     ["test_evidence_is_uploaded_even_when_tests_fail"]),
    ("S17", "결함 복원", "잡 defaults.run.working-directory — 스텝 검사 우회 (D-071)", W, ST,
     [("    runs-on: ubuntu-24.04\n",
       "    runs-on: ubuntu-24.04\n    defaults:\n      run:\n        working-directory: gateway\n")],
     ["test_no_default_directory_shell_or_other_image"]),
    ("S18", "결함 복원", "잡 container — 다른 이미지에서 실행(V2) (D-071)", W, ST,
     [("    runs-on: ubuntu-24.04\n", "    runs-on: ubuntu-24.04\n    container: python:3.12\n")],
     ["test_no_default_directory_shell_or_other_image"]),
    ("S19", "결함 복원", "runs-on: ubuntu-latest (D-071)", W, ST,
     [("    runs-on: ubuntu-24.04\n", "    runs-on: ubuntu-latest\n")],
     ["test_runner_is_the_one_d069_describes"]),

    # ---- 무해 변경: 통과해야 한다 (과잉 수정 방지)
    ("P1", "무해 변경", "스텝 name 변경", W, ST,
     [("        name: Install (README 6절 그대로)\n", "        name: 설치\n")], []),
    ("P2", "무해 변경", "README 6절 uvicorn 데모 블록 변경", R, ST,
     [("uvicorn tests.stub_target:app --port 8000", "uvicorn tests.stub_target:app --port 8001")], []),
    ("P3", "무해 변경", "README 7절 변경", R, ST,
     [("tests/      단위·통합 테스트 + 가짜 타겟\n", "tests/      단위·통합 테스트 + 가짜 타겟 + CI 동기화 검사\n")], []),
    ("P4", "무해 변경", "README 설치 블록에 빈 줄·들여쓰기", R, ST,
     [("cd llm-security-gateway\npython3 -m venv .venv\nsource .venv/bin/activate\n",
       "cd llm-security-gateway\n\npython3 -m venv .venv\n  source .venv/bin/activate\n")], []),
    ("P5", "무해 변경", "upload-artifact 입력 변경(name·retention-days)", W, ST,
     [("          name: ci-evidence-py${{ matrix.python }}\n",
       "          name: evidence-${{ matrix.python }}\n          retention-days: 30\n")], []),
    ("P6", "무해 변경", "junit if를 always()로 — 같은 동작", W, ST,
     [("        if: ${{ !cancelled() }}\n        run: python3 scripts/ci_junit_check.py junit.xml\n",
       "        if: ${{ always() }}\n        run: python3 scripts/ci_junit_check.py junit.xml\n")], []),
]


def run(root: pathlib.Path, test_file: str) -> tuple[int, ET.Element, str]:
    report = root / "mutation-report.xml"
    report.unlink(missing_ok=True)
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", test_file, "-q",
                        "-p", "no:cacheprovider", "--tb=line", f"--junitxml={report}"],
                       cwd=root, capture_output=True, text=True,
                       env={k: v for k, v in __import__("os").environ.items()
                            if k != "PYTEST_ADDOPTS"})
    if not report.exists():
        raise RuntimeError("pytest가 보고서를 쓰지 않았다\n" + p.stdout + p.stderr)
    return p.returncode, ET.parse(report).getroot(), p.stdout + p.stderr


def failed_tests(report: ET.Element) -> tuple[set[str], list[str], bool]:
    """(assert로 실패한 테스트 이름, 그 밖의 문제, 오류 존재 여부)."""
    names, other = set(), []
    for c in report.iter("testcase"):
        f = c.find("failure")
        if f is not None:
            msg = f.get("message", "")
            if msg.startswith(("AssertionError", "assert ")):
                names.add(c.get("name"))
            else:
                other.append(f"{c.get('name')}: {msg[:120]}")
    for c in report.iter("testcase"):
        if c.find("skipped") is not None:
            other.append(f"{c.get('name')}: skip")
    return names, other, report.find(".//error") is not None


def main() -> int:
    files = sorted({m[3] for m in MUTATIONS} | {m[4] for m in MUTATIONS})
    with tempfile.TemporaryDirectory(prefix="ci-mutations-") as tmp:
        root = pathlib.Path(tmp)
        for f in files:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, root / f)
        originals = {f: (root / f).read_text(encoding="utf-8") for f in files}

        test_files = sorted({m[4] for m in MUTATIONS})
        baseline: dict[str, int] = {}
        for tf in test_files:
            code, report, out = run(root, tf)
            n = len(list(report.iter("testcase")))
            if code != 0:
                print(f"기준선 실패: {tf}\n{out}")
                return 1
            baseline[tf] = n
            print(f"기준선: {tf} {n} passed", flush=True)

        missed = []
        for mid, kind, desc, target, tf, edits, expect in MUTATIONS:
            src = originals[target]
            mutated = src
            for old, new in edits:
                if mutated.count(old) != 1:
                    raise RuntimeError(f"{mid}: 앵커가 유일하지 않다 ({mutated.count(old)}회): {old!r}")
                mutated = mutated.replace(old, new)
            if mutated == src:
                raise RuntimeError(f"{mid}: 변이가 아무것도 바꾸지 않았다")
            if target.endswith(".py"):
                compile(mutated, target, "exec")
            elif target.endswith((".yml", ".yaml")):
                import yaml
                yaml.safe_load(mutated)
            (root / target).write_text(mutated, encoding="utf-8")
            try:
                code, report, out = run(root, tf)
            finally:
                (root / target).write_text(src, encoding="utf-8")
            names, other, has_error = failed_tests(report)
            if kind in PASS_KINDS:
                n = len(list(report.iter("testcase")))
                missing = []
                ok = code == 0 and not names and not other and not has_error and n == baseline[tf]
                print(f"{mid} [{kind}] {desc}: {'통과 유지' if ok else '★ 과잉 검출'} "
                      f"(테스트 {n}개/기준 {baseline[tf]}개, 실패 {len(names)}개)", flush=True)
                if names:
                    print(f"    무해한 변경에 실패한 테스트: {sorted(names)}")
            else:
                missing = [t for t in expect if t not in names]
                ok = code == 1 and not missing and not other and not has_error
                print(f"{mid} [{kind}] {desc}: {'검출' if ok else '★ 검증 실패'} "
                      f"(실패 {len(names)}개, 지정 {len(expect)}개)", flush=True)
            if not ok:
                missed.append(mid)
                if missing:
                    print(f"    지정했지만 실패하지 않은 테스트: {missing}")
                for o in other:
                    print(f"    assert가 아닌 실패: {o}")
                if has_error:
                    print("    수집·설정 오류가 있다")

    print("-" * 60)
    must_fail = [m for m in MUTATIONS if m[1] not in PASS_KINDS]
    must_pass = [m for m in MUTATIONS if m[1] in PASS_KINDS]
    miss_f = [m[0] for m in must_fail if m[0] in missed]
    miss_p = [m[0] for m in must_pass if m[0] in missed]
    print(f"잡혀야 함 {len(must_fail) - len(miss_f)}/{len(must_fail)} 검출, "
          f"통과해야 함 {len(must_pass) - len(miss_p)}/{len(must_pass)} 통과. 원본 파일 무수정.")
    if missed:
        print(f"검증 실패: {', '.join(missed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
