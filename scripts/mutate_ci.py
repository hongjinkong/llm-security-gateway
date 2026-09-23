#!/usr/bin/env python3
"""D-069 변이 검사 — CI 판정 도구의 테스트가 실제 문제를 잡는지 확인한다.

`scripts/mutate_audit_vault.py`와 같은 방식이다. **임시 복사본만 바꾼다.**
원본은 건드리지 않으므로 중간에 죽어도 되돌릴 것이 없다.

두 종류를 함께 넣는다(D-067 4절).
  - 결함 복원: 막으려던 문제를 되살린다 → 지정한 테스트가 실패해야 한다
  - 과잉 수정·부작용: 정상인 것까지 막거나 보고 숫자를 오염시킨다 → 역시 실패해야 한다
    결함 복원만으로는 "고쳤다"와 "기능을 죽였다"를 구분하지 못한다.

검출의 조건: 지정한 테스트가 **전부** 실패했고, 실패가 assert 실패이며, 수집·설정 오류가
없다. 변이가 문법을 깨서 "실패"가 나온 것은 검출로 세지 않는다.

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
        for tf in test_files:
            code, report, out = run(root, tf)
            n = len(list(report.iter("testcase")))
            if code != 0:
                print(f"기준선 실패: {tf}\n{out}")
                return 1
            print(f"기준선: {tf} {n} passed", flush=True)

        missed = []
        for mid, kind, desc, target, tf, edits, expect in MUTATIONS:
            src = originals[target]
            mutated = src
            for old, new in edits:
                if mutated.count(old) != 1:
                    raise RuntimeError(f"{mid}: 앵커가 유일하지 않다 ({mutated.count(old)}회): {old!r}")
                mutated = mutated.replace(old, new)
            if target.endswith(".py"):
                compile(mutated, target, "exec")
            (root / target).write_text(mutated, encoding="utf-8")
            try:
                code, report, out = run(root, tf)
            finally:
                (root / target).write_text(src, encoding="utf-8")
            names, other, has_error = failed_tests(report)
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
    print(f"{len(MUTATIONS) - len(missed)}/{len(MUTATIONS)} 검출. 원본 파일 무수정.")
    if missed:
        print(f"검출 실패: {', '.join(missed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
