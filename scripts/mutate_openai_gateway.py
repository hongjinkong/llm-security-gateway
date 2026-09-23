#!/usr/bin/env python3
"""D-074 OpenAI 입구 테스트의 결함 검출·과잉 검출 여부를 임시 복사본에서 확인한다."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST = "tests/test_openai_gateway.py"
TARGET = "gateway/openai_api.py"

# (id, 종류, 설명, [(기존, 변이)], 실패해야 하는 테스트)
MUTATIONS = [
    ("D1", "결함 복원", "식별 가능한 RAG(tool)를 인젝션 검사에서 뺀다", [
        ('INJECTION_ROLES = frozenset({"user", "tool"})',
         'INJECTION_ROLES = frozenset({"user"})'),
    ], ["test_injection_scope_is_user_and_tool_text_only",
        "test_tool_injection_returns_openai_block_completion"]),
    ("D2", "결함 복원", "stream=true를 상류로 통과시킨다", [
        ("    if stream:\n", "    if False:\n"),
    ], ["test_stream_true_is_rejected_with_openai_error"]),
    ("O1", "과잉 수정·부작용", "system·tool의 PII까지 마스킹한다", [
        ('PII_ROLES = frozenset({"user"})',
         'PII_ROLES = frozenset({"system", "user", "tool"})'),
    ], ["test_pii_masking_changes_only_user_messages",
        "test_user_pii_is_masked_upstream_and_restored_in_completion"]),
    ("P1", "무해 변경", "검증 오류의 설명 문구만 바꾼다", [
        ('messages must be a non-empty array', 'messages must contain at least one item'),
    ], []),
]


def run(root: pathlib.Path) -> tuple[int, ET.Element, str]:
    report = root / "mutation-report.xml"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("GATEWAY_DETECTORS", None)
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider",
         "--tb=line", f"--junitxml={report}"],
        cwd=root, capture_output=True, text=True, env=env,
    )
    if not report.exists():
        raise RuntimeError("pytest가 junit을 만들지 않았다\n" + proc.stdout + proc.stderr)
    return proc.returncode, ET.parse(report).getroot(), proc.stdout + proc.stderr


def problems(report: ET.Element) -> tuple[set[str], list[str]]:
    failed, other = set(), []
    for case in report.iter("testcase"):
        if case.find("failure") is not None:
            failed.add(case.get("name", ""))
        if case.find("error") is not None:
            other.append(f"{case.get('name')}: error")
        if case.find("skipped") is not None:
            other.append(f"{case.get('name')}: skipped")
    return failed, other


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="openai-gateway-mutations-") as tmp:
        root = pathlib.Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        shutil.copytree(ROOT / "gateway", root / "gateway", ignore=ignore)
        shutil.copytree(ROOT / "tests", root / "tests", ignore=ignore)

        code, report, out = run(root)
        baseline = len(list(report.iter("testcase")))
        if code != 0:
            print("기준선 실패\n" + out)
            return 1
        print(f"기준선: {baseline} passed", flush=True)

        path = root / TARGET
        original = path.read_text(encoding="utf-8")
        missed: list[str] = []
        for mid, kind, desc, edits, expected in MUTATIONS:
            mutated = original
            for old, new in edits:
                if mutated.count(old) != 1:
                    raise RuntimeError(f"{mid}: 앵커가 유일하지 않다 ({mutated.count(old)}회)")
                mutated = mutated.replace(old, new)
            compile(mutated, TARGET, "exec")
            path.write_text(mutated, encoding="utf-8")
            try:
                code, report, _ = run(root)
            finally:
                path.write_text(original, encoding="utf-8")
            failed, other = problems(report)
            count = len(list(report.iter("testcase")))
            if kind == "무해 변경":
                ok = code == 0 and count == baseline and not failed and not other
                detail = f"테스트 {count}개/기준 {baseline}개"
            else:
                missing = sorted(set(expected) - failed)
                ok = code == 1 and not missing and not other
                detail = f"실패 {len(failed)}개, 지정 {len(expected)}개"
                if missing:
                    detail += f", 미검출 {missing}"
            print(f"{mid} [{kind}] {desc}: {'통과' if ok else '★ 검증 실패'} ({detail})",
                  flush=True)
            if not ok:
                missed.append(mid)

    print(f"결과: {len(MUTATIONS) - len(missed)}/{len(MUTATIONS)} 통과. 원본 파일 무수정.")
    if missed:
        print("검증 실패: " + ", ".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
