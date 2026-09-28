#!/usr/bin/env python3
"""D-082 target_settings.py 테스트를 임시 복사본에서 변이 검사한다."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = "eval/target_settings.py"
FILES = [TARGET, "tests/test_setup_target.py"]
TESTS = ["tests/test_setup_target.py"]

# (id, 종류, 설명, 파일, 기존, 변이, 실패해야 하는 테스트)
MUTATIONS = [
    ("D1", "결함 복원", "설정에서 chatProvider를 뺀다(개별값 ollama를 못 잡는다)", TARGET,
     '    "chatProvider": None,\n', "",
     "test_t2_stored_ollama_provider_is_a_mismatch"),
    ("D2", "결함 복원", "w.get 비교로 되돌린다(키가 없어도 null로 통과)", TARGET,
     '        if k not in w:\n'
     '            out.append(f"불일치 {k}: 기대 {v!r} / 실제 (키 없음)")\n'
     '        elif w[k] != v:',
     '        if w.get(k) != v:',
     "test_t3_missing_key_is_not_treated_as_null"),
    ("O1", "과잉 수정·부작용", "chatProvider를 generic-openai로 명시한다(스위치가 두 곳)", TARGET,
     '    "chatProvider": None,\n', '    "chatProvider": "generic-openai",\n',
     "test_t1_settings_clear_provider_and_keep_frozen_values"),
    ("O2", "과잉 수정·부작용", "동결값 openAiTemp를 검증에서 빠뜨린다", TARGET,
     '    "openAiTemp": 0.7,\n', "",
     "test_t1_settings_clear_provider_and_keep_frozen_values"),
    ("P1", "무해 변경", "docstring 문구만 바꾼다", TARGET,
     "네트워크·환경변수를 쓰지 않으므로 테스트에서 그대로 불러온다.",
     "네트워크와 환경변수 없이 테스트에서 불러온다.", None),
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
    with tempfile.TemporaryDirectory(prefix="setup-target-mutations-") as tmp:
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
