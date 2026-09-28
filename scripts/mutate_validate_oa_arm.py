#!/usr/bin/env python3
"""D-081 validate_oa_arm.py 테스트를 임시 복사본에서 변이 검사한다."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = "scripts/validate_oa_arm.py"
FILES = [TARGET, "tests/test_validate_oa_arm.py"]
TESTS = ["tests/test_validate_oa_arm.py"]

# (id, 종류, 설명, 파일, 기존, 변이, 실패해야 하는 테스트)
MUTATIONS = [
    ("D1", "결함 복원", "감사 줄 수와 garak 출력 수를 대조하지 않는다", TARGET,
     "require(len(rows) == outputs,", "require(True,",
     "test_E3_감사_줄이_하나_많다"),
    ("D2", "결함 복원", "--audit-from을 무시하고 앞에 쌓인 FPR 줄까지 센다", TARGET,
     ")[start:]", ")",
     "test_앞에_쌓인_감사_줄은_세지_않는다"),
    ("D3", "결함 복원", "none 팔의 차단을 허용한다", TARGET,
     'require(arm != "none" or blocked == 0,', "require(True,",
     "test_E3_none_팔에_차단이_있다"),
    ("D4", "결함 복원", "경로 검사를 뺀다(옛 경로 혼입을 못 잡는다)", TARGET,
     "require(all(r.get(\"path\") == CHAT_PATH for r in rows),", "require(True,",
     "test_E3_다른_경로"),
    ("D5", "결함 복원", "두 팔의 프롬프트 해시를 비교하지 않는다", TARGET,
     "require(not diff,", "require(True,",
     "test_E5_프롬프트가_하나_다르다"),
    ("D6", "결함 복원", "출력 수가 10개가 아니어도 받는다", TARGET,
     "len(outs) == GENERATIONS", "len(outs) >= 1",
     "test_E1_출력이_10개가_아니다"),
    ("O1", "과잉 수정·부작용", "rule 팔의 차단도 무효로 본다", TARGET,
     'require(arm != "none" or blocked == 0,', "require(blocked == 0,",
     "test_rule_팔은_차단_수를_보고한다"),
    ("P1", "무해 변경", "docstring 문구만 바꾼다", TARGET,
     "새 채점 규칙은 없다.", "채점 규칙을 새로 만들지 않는다.", None),
]


def run(root: pathlib.Path) -> tuple[int, ET.Element, str]:
    report = root / "mutation-report.xml"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider",
         "--tb=line", f"--junitxml={report}"],
        cwd=root, capture_output=True, text=True, env=env,
    )
    if not report.exists():
        raise RuntimeError("테스트가 junit을 만들지 않았다\n" + proc.stdout + proc.stderr)
    return proc.returncode, ET.parse(report).getroot(), proc.stdout + proc.stderr


def results(report: ET.Element) -> tuple[set[str], list[str]]:
    failed: set[str] = set()
    other: list[str] = []
    for case in report.iter("testcase"):
        name = case.get("name", "")
        if case.find("failure") is not None:
            failed.add(name)
        if case.find("error") is not None:
            other.append(f"{name}: error")
        if case.find("skipped") is not None:
            other.append(f"{name}: skipped")
    return failed, other


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="oa-arm-mutations-") as tmp:
        root = pathlib.Path(tmp)
        for f in FILES:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, root / f)

        code, report, out = run(root)
        baseline = len(list(report.iter("testcase")))
        if code != 0:
            print("기준선 실패\n" + out)
            return 1
        print(f"기준선: {baseline} passed", flush=True)

        missed: list[str] = []
        for mid, kind, desc, target, old, new, expected in MUTATIONS:
            path = root / target
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                raise RuntimeError(f"{mid}: 앵커가 유일하지 않다 ({original.count(old)}회)")
            path.write_text(original.replace(old, new), encoding="utf-8")
            try:
                code, report, _ = run(root)
            finally:
                path.write_text(original, encoding="utf-8")

            failed, other = results(report)
            count = len(list(report.iter("testcase")))
            if expected is None:
                ok = code == 0 and count == baseline and not failed and not other
                detail = f"테스트 {count}개/기준 {baseline}개"
            else:
                ok = code == 1 and expected in failed and not other
                detail = f"실패 {len(failed)}개, 지정 1개"
            print(f"{mid} [{kind}] {desc}: {'통과' if ok else '★ 검증 실패'} ({detail})",
                  flush=True)
            if not ok:
                missed.append(mid)

    print(f"결과: {len(MUTATIONS) - len(missed)}/{len(MUTATIONS)} 통과. 원본 파일 무수정.")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
