#!/usr/bin/env python3
"""D-075 Compose 계약 테스트를 임시 복사본에서 변이 검사한다."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = "docker-compose.yml"
TEST = "tests/test_openai_compose.py"

# (id, 종류, 설명, 기존, 변이, 실패해야 하는 테스트)
MUTATIONS = [
    ("D1", "결함 복원", "AnythingLLM이 gateway를 우회해 Ollama를 직접 호출한다",
     "GENERIC_OPEN_AI_BASE_PATH=http://gateway:8080/v1",
     "GENERIC_OPEN_AI_BASE_PATH=http://host.docker.internal:11434/v1",
     "test_generic_openai_mode_routes_through_gateway_without_streaming"),
    ("D2", "결함 복원", "Agent 비스트리밍 별칭을 뺀다",
     "      - GENERIC_OPENAI_STREAMING_DISABLED=true\n", "",
     "test_generic_openai_mode_routes_through_gateway_without_streaming"),
    ("D3", "결함 복원", "일반 채팅 비스트리밍 별칭을 뺀다",
     "      - GENERIC_OPEN_AI_STREAMING_DISABLED=true\n", "",
     "test_generic_openai_mode_routes_through_gateway_without_streaming"),
    ("O1", "과잉 수정·부작용", "기존 기본 모드도 generic-openai로 바꿔버린다",
     "LLM_PROVIDER=${ANYTHINGLLM_LLM_PROVIDER:-ollama}",
     "LLM_PROVIDER=${ANYTHINGLLM_LLM_PROVIDER:-generic-openai}",
     "test_existing_ollama_route_remains_the_default"),
    ("P1", "무해 변경", "Compose 주석 문구만 바꾼다",
     "# B2: AnythingLLM Generic OpenAI → gateway → 로컬 Ollama.",
     "# B2 로컬 경로: AnythingLLM → gateway → Ollama.", None),
]


def run(root: pathlib.Path) -> tuple[int, ET.Element, str]:
    report = root / "mutation-report.xml"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider",
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
    with tempfile.TemporaryDirectory(prefix="openai-compose-mutations-") as tmp:
        root = pathlib.Path(tmp)
        (root / "tests").mkdir()
        shutil.copy2(ROOT / TARGET, root / TARGET)
        shutil.copy2(ROOT / TEST, root / TEST)

        code, report, out = run(root)
        baseline = len(list(report.iter("testcase")))
        if code != 0:
            print("기준선 실패\n" + out)
            return 1
        print(f"기준선: {baseline} passed", flush=True)

        path = root / TARGET
        original = path.read_text(encoding="utf-8")
        missed: list[str] = []
        for mid, kind, desc, old, new, expected in MUTATIONS:
            if original.count(old) != 1:
                raise RuntimeError(f"{mid}: 앵커가 유일하지 않다 ({original.count(old)}회)")
            mutated = original.replace(old, new)
            yaml.safe_load(mutated)
            path.write_text(mutated, encoding="utf-8")
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
