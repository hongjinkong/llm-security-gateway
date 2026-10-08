#!/usr/bin/env python3
"""D-094 d094_alone_vs_actual.py 테스트를 임시 복사본에서 변이 검사한다."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = "scripts/d094_alone_vs_actual.py"
FILES = [TARGET, "scripts/rescore_blocking.py", "tests/test_d094.py"]
TESTS = ["tests/test_d094.py"]

# (id, 종류, 설명, 파일, 기존, 변이, 실패해야 하는 테스트)
MUTATIONS = [
    ("D1", "결함", "단독 판정이 검사기를 부르지 않는다(항상 통과)", TARGET,
     "return asyncio.run(DETECTOR.inspect(insp)).action is Action.BLOCK", "return False",
     "test_단독_판정은_실제_검사기를_부른다"),
    ("D2", "결함", "핵심 칸을 단독 차단 쪽으로 센다", TARGET,
     "if s and at.alone:", "if s and not at.alone:",
     "test_2x2와_핵심_칸"),
    ("D3", "결함", "S1을 부분 포함으로 본다", TARGET,
     'is_blocked(o.get("text") if isinstance(o, dict) else o, DEFAULT_BLOCKED_MESSAGE)',
     'DEFAULT_BLOCKED_MESSAGE in (o.get("text") if isinstance(o, dict) else o)',
     "test_S1은_전체_일치만_차단으로_본다"),
    ("D4", "결함", "status 1 attempt도 읽는다(출력 이중 계산)", TARGET,
     'row.get("status") != 2', 'row.get("status") not in (1, 2)',
     "test_리포트는_status_2만_읽고_단독_판정과_S1을_붙인다"),
    ("D5", "결함", "감사 줄 수를 대조하지 않는다", TARGET,
     "if len(audit) != len(s1):", "if False:",
     "test_정렬_감사_줄_수가_다르면_실패"),
    ("D6", "결함", "감사 차단 ∧ S1 통과를 보지 않는다", TARGET,
     'return f"감사 차단 ∧ S1 통과 {reverse}개" if reverse else None', "return None",
     "test_정렬_감사_차단인데_S1_통과면_실패"),
    ("D7", "결함", "audit_from 앞줄(FPR 등)까지 센다", TARGET,
     '_rows(path, "감사 사본")[start:]', '_rows(path, "감사 사본")',
     "test_audit_from_앞줄은_세지_않는다"),
    ("D8", "결함", "보조 B가 팔 첫 요청부터 센다(창이 앞 팔로 넘어간다)", TARGET,
     "for i in range(WINDOW, len(alone)):", "for i in range(1, len(alone)):",
     "test_거리_d는_가장_가까운_단독_차단까지이고_21번째부터_센다"),
    ("D9", "결함", "거리 d를 하나 작게 센다", TARGET,
     "return dist\n", "return dist - 1\n",
     "test_거리_d는_가장_가까운_단독_차단까지이고_21번째부터_센다"),
    ("D10", "결함", "정렬이 실패해도 보조 분석을 낸다", TARGET,
     "reason = align(s1, audit)", "reason = None",
     "test_정렬이_실패하면_보조_A_B를_내지_않는다"),
    ("D11", "결함", "양성 대조 불일치 위치를 적지 않는다", TARGET,
     "keys = [(at.probe, at.seq) for at in attempts if any(s != at.alone for s in at.s1)]", "keys = []",
     "test_전체_출력_수치"),
    ("D12", "결함", "프롬프트 앞부분이 출력에 섞인다(D-039 위반)", TARGET,
     "out.append(Attempt(key[0], key[1], alone_blocked(text), s1))",
     "out.append(Attempt(text[:40], key[1], alone_blocked(text), s1))",
     "test_전체_출력은_원문을_쓰지_않는다"),
    ("D13", "결함", "입력 오류 문구에 turn 내용을 넣는다(D-039 위반)", TARGET,
     "turn {len(turns)}개 —", "turn {turns} —",
     "test_입력_오류_문구에_원문이_없다"),
    ("D14", "결함", "등록된 audit_from이 바뀐다", TARGET,
     '"results/audit_oa_pi_20260928_01.jsonl", 13254),', '"results/audit_oa_pi_20260928_01.jsonl", 13255),',
     "test_등록된_입력표는_D094와_같다"),
    ("O1", "과잉 수정", "모델이 낸 차단 문구(S1 차단 ∧ 감사 통과)도 정렬 실패로 본다", TARGET,
     "if au and not s)", "if au != s)",
     "test_모델이_낸_차단_문구는_정렬을_깨지_않는다"),
    ("P1", "무해 변경", "docstring 문구만 바꾼다", TARGET,
     "종료 코드: 0 대조 완료(수치는 출력에) / 2 입력 오류", "종료 코드: 0 대조 끝(수치는 출력에) / 2 입력 오류", None),
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
    with tempfile.TemporaryDirectory(prefix="d094-mutations-") as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(ROOT / "gateway", root / "gateway",
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
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
            print(f"{mid} [{kind}] {desc}: {'통과' if ok else '★ 검증 실패'} ({detail})", flush=True)
            if not ok:
                missed.append(mid)

    print(f"결과: {len(MUTATIONS) - len(missed)}/{len(MUTATIONS)} 통과. 원본 파일 무수정.")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
