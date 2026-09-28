#!/usr/bin/env python3
"""D-081 P3 `fpr_report.py --link time` 테스트를 임시 복사본에서 변이 검사한다."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT = "scripts/fpr_report.py"
RUNNER = "eval/fpr_run.py"
FILES = [REPORT, RUNNER, "tests/test_fpr_report.py", "tests/test_fpr_link_time.py"]
TESTS = ["tests/test_fpr_report.py", "tests/test_fpr_link_time.py"]

# (id, 종류, 설명, 파일, 기존, 변이, 실패해야 하는 테스트)
MUTATIONS = [
    ("D1", "결함 복원", "창 안 감사 줄이 둘이어도 첫 줄로 잇는다", REPORT,
     "if len(hits[id(r)]) != 1]", "if not hits[id(r)]]",
     "test_T2_창_하나에_감사_줄이_둘"),
    ("D2", "결함 복원", "어느 창에도 없는 감사 줄을 무시한다", REPORT,
     "    if stray:\n", "    if False:\n",
     "test_T3_어느_창에도_속하지_않는_감사_줄"),
    ("D3", "결함 복원", "창 겹침 검사를 뺀다", REPORT,
     "        if start <= prev_end:\n", "        if False:\n",
     "test_T5_창이_겹친다"),
    ("D4", "결함 복원", "fpr_run.py가 호출 창을 남기지 않는다", RUNNER,
     '    return {**r, "t_start": t_start, "t_end": utcnow()}', "    return r",
     "test_fpr_run은_감사_로그와_같은_형식으로_창을_남긴다"),
    ("O1", "과잉 수정·부작용", "창 경계를 제외한다(엄격 비교)", REPORT,
     "start <= ts <= end", "start < ts < end",
     "test_창의_양끝에_찍힌_감사_줄도_잇는다"),
    ("O2", "과잉 수정·부작용", "기본 연결을 time으로 바꿔 옛 경로를 깬다", REPORT,
     'default="header"', 'default="time"',
     "test_기본값은_여전히_헤더_연결이다"),
    ("P1", "무해 변경", "주석 문구만 바꾼다", REPORT,
     "# ponytail: O(실행 x 감사 줄) 스캔.", "# ponytail: 실행 x 감사 줄 전수 스캔.", None),
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
    with tempfile.TemporaryDirectory(prefix="fpr-link-mutations-") as tmp:
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
