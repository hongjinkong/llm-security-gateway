"""D-069: `scripts/ci_junit_check.py` — CI의 pytest 결과(junit XML) 판정.

**이 파일은 `scripts/ci_junit_check.py`보다 먼저 쓰였다.**

왜 판정기가 따로 필요한가. `pytest -q`의 종료 코드 0은 "실패·오류가 없다"만 말한다.
새 체크아웃에서 파일이 없어 테스트가 **건너뛰어져도** 종료 코드는 0이다. 그러면 CI는
초록불인데 실제로는 검사하지 않은 테스트가 섞여 있다. D-069 A4는 skip 0을 요구한다.

종료 코드 계약 (D-064와 같은 세 갈래):
    0  합격 — 테스트 >0, 실패·오류·skip 0, 요약 속성과 개별 결과 일치
    1  불합격 — 실패·오류·skip(xfail 포함)이 있다
    2  무효 — 파일 없음, 파싱 실패, 테스트 0개, 요약과 개별 결과 불일치.
       **자료의 부재는 결과가 아니다.**

junit은 가능한 한 **진짜 pytest로 만든다.** 판정기가 내가 상상한 형식이 아니라
pytest가 실제로 내는 형식을 읽는지 확인하기 위해서다. pytest가 만들 수 없는
손상 파일만 손으로 쓴다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_junit_check.py"
SUMMARY = re.compile(
    r"^junit: tests=(\d+) passed=(\d+) failures=(\d+) errors=(\d+) skipped=(\d+)$", re.M)


def check(xml: Path) -> subprocess.CompletedProcess:
    assert SCRIPT.exists(), f"판정기가 아직 없다: {SCRIPT}"
    return subprocess.run([sys.executable, str(SCRIPT), str(xml)],
                          capture_output=True, text=True)


def summary(out: str) -> tuple[int, ...]:
    """판정기가 찍은 요약 줄을 숫자로. 경로 문자열에 휘둘리지 않게 줄 전체를 맞춘다."""
    m = SUMMARY.search(out)
    assert m, f"요약 줄이 없다:\n{out}"
    return tuple(int(x) for x in m.groups())


def real_junit(tmp_path: Path, source: str, *extra: str) -> Path:
    """tmp_path에 테스트 파일 하나를 두고 **진짜 pytest**로 junit을 만든다.

    CI는 PYTEST_ADDOPTS로 --junitxml을 넘긴다. 그 값이 이 하위 pytest에 새어
    들어가면 엉뚱한 곳에 파일을 쓰므로 환경에서 뺀다. 저장소의 conftest가 끼지 않게
    rootdir도 tmp_path로 고정한다.
    """
    (tmp_path / "test_sample.py").write_text(textwrap.dedent(source), encoding="utf-8")
    xml = tmp_path / "junit.xml"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                    f"--rootdir={tmp_path}", f"--junitxml={xml}", *extra,
                    str(tmp_path / "test_sample.py")],
                   cwd=tmp_path, env=env, capture_output=True, text=True)
    assert xml.exists(), "pytest가 junit을 쓰지 않았다 — 픽스처 자체가 깨졌다"
    return xml


PASS2 = """
    def test_a():
        assert 1 + 1 == 2

    def test_b():
        assert "a" in "abc"
"""


# ---------------------------------------------------------------- 합격 (0)

def test_all_passing_is_accepted_and_counted(tmp_path):
    r = check(real_junit(tmp_path, PASS2))
    assert r.returncode == 0, r.stdout + r.stderr
    assert summary(r.stdout) == (2, 2, 0, 0, 0)


def test_captured_output_and_properties_do_not_count_as_problems(tmp_path):
    """과잉 수정 방지: testcase 안의 <system-out>·<properties>는 실패가 아니다."""
    src = """
        def test_prints(record_property):
            record_property("fixture", "x")
            print("로그 한 줄")
            assert True
    """
    r = check(real_junit(tmp_path, src, "-o", "junit_logging=all"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert summary(r.stdout) == (1, 1, 0, 0, 0)


def test_bare_testsuite_root_is_accepted(tmp_path):
    """과잉 수정 방지: <testsuites> 감싸개가 없는 단일 <testsuite> 뿌리도 읽는다."""
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1">'
        '<testcase classname="t" name="a" time="0.1"/></testsuite>', encoding="utf-8")
    r = check(xml)
    assert r.returncode == 0, r.stdout + r.stderr
    assert summary(r.stdout) == (1, 1, 0, 0, 0)


# ---------------------------------------------------------------- 불합격 (1)

def test_skip_is_rejected(tmp_path):
    """이 판정기가 있는 이유. pytest 종료 코드는 0이지만 CI는 불합격이어야 한다."""
    src = PASS2 + """
    import pytest

    def test_c():
        pytest.skip("파일 없음")
    """
    r = check(real_junit(tmp_path, src))
    assert r.returncode == 1, r.stdout + r.stderr
    assert summary(r.stdout) == (3, 2, 0, 0, 1)


def test_xfail_is_rejected(tmp_path):
    """pytest는 xfail을 junit에 skipped로 적는다. 알려진 실패도 합격이 아니다."""
    src = PASS2 + """
    import pytest

    @pytest.mark.xfail(reason="알려진 결함")
    def test_c():
        assert False
    """
    r = check(real_junit(tmp_path, src))
    assert r.returncode == 1, r.stdout + r.stderr
    assert summary(r.stdout) == (3, 2, 0, 0, 1)


def test_failure_is_rejected(tmp_path):
    src = PASS2 + """
    def test_c():
        assert 1 == 2
    """
    r = check(real_junit(tmp_path, src))
    assert r.returncode == 1, r.stdout + r.stderr
    assert summary(r.stdout) == (3, 2, 1, 0, 0)


def test_fixture_error_is_rejected(tmp_path):
    src = PASS2 + """
    import pytest

    @pytest.fixture
    def broken():
        raise RuntimeError("setup 실패")

    def test_c(broken):
        assert True
    """
    r = check(real_junit(tmp_path, src))
    assert r.returncode == 1, r.stdout + r.stderr
    assert summary(r.stdout) == (3, 2, 0, 1, 0)


def test_collection_error_is_rejected(tmp_path):
    """새 체크아웃에서 의존성이 빠지면 여기로 온다(ModuleNotFoundError)."""
    src = """
        import no_such_module_d069

        def test_a():
            assert True
    """
    r = check(real_junit(tmp_path, src))
    assert r.returncode == 1, r.stdout + r.stderr
    assert summary(r.stdout)[3] >= 1


# ---------------------------------------------------------------- 무효 (2)

def test_missing_file_is_invalid(tmp_path):
    r = check(tmp_path / "junit.xml")
    assert r.returncode == 2, r.stdout + r.stderr


def test_truncated_file_is_invalid(tmp_path):
    xml = real_junit(tmp_path, PASS2)
    data = xml.read_text(encoding="utf-8")
    xml.write_text(data[: len(data) // 2], encoding="utf-8")
    r = check(xml)
    assert r.returncode == 2, r.stdout + r.stderr


def test_empty_file_is_invalid(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text("", encoding="utf-8")
    r = check(xml)
    assert r.returncode == 2, r.stdout + r.stderr


def test_zero_tests_is_invalid(tmp_path):
    """테스트가 하나도 안 돌았으면 '문제 없음'이 아니라 '자료 없음'이다."""
    r = check(real_junit(tmp_path, "X = 1\n"))
    assert r.returncode == 2, r.stdout + r.stderr


def test_non_junit_root_is_invalid(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text("<html><body>not junit</body></html>", encoding="utf-8")
    r = check(xml)
    assert r.returncode == 2, r.stdout + r.stderr


def test_summary_hiding_a_skip_is_invalid(tmp_path):
    """요약 속성은 skipped=0인데 개별 결과에 skip이 있다 — 어느 쪽도 믿을 수 없다."""
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2">'
        '<testcase classname="t" name="a"/>'
        '<testcase classname="t" name="b"><skipped message="x"/></testcase>'
        '</testsuite></testsuites>', encoding="utf-8")
    r = check(xml)
    assert r.returncode == 2, r.stdout + r.stderr


def test_summary_count_not_matching_testcases_is_invalid(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="5">'
        '<testcase classname="t" name="a"/><testcase classname="t" name="b"/>'
        '</testsuite></testsuites>', encoding="utf-8")
    r = check(xml)
    assert r.returncode == 2, r.stdout + r.stderr


def test_missing_summary_attribute_is_invalid(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<testsuites><testsuite name="pytest" errors="0" failures="0" tests="1">'
        '<testcase classname="t" name="a"/></testsuite></testsuites>', encoding="utf-8")
    r = check(xml)
    assert r.returncode == 2, r.stdout + r.stderr
