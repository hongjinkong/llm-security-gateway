#!/usr/bin/env python3
"""D-062 변이 7종. 임시 복사본만 바꾸며 원본 코드·측정 자료는 건드리지 않는다.

사용: python3 scripts/mutate_cluster_ci.py
기준선 통과 후 pytest의 assertion 실패만 검출로 센다(실행/수집 오류는 실패).
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAW = "    vals = [ratio([cl[rng.randrange(m)] for _ in range(m)]) for _ in range(B)]"
MUTATIONS = [
    ("M1 출력 단위 재표집", DRAW,
     "    outputs = [1] * sum(k for k, n in cl) + [0] * sum(n-k for k, n in cl)\n"
     "    vals = [sum(rng.choices(outputs, k=len(outputs))) / len(outputs) for _ in range(B)]",
     "test_c4_rho1_폭이_Wilson의_루트10배_안팎이다"),
    ("M2 비복원추출", DRAW,
     "    vals = [ratio(rng.sample(cl, m)) for _ in range(B)]",
     "test_변이2_CI_폭이_0이_아니다"),
    ("M3 군집 고정 후 군집 내부만 재표집", DRAW,
     "    vals = [ratio([(sum(rng.random() < k/n for _ in range(n)), n)\n"
     "                   for k, n in cl]) for _ in range(B)]",
     "test_c4_rho1_폭이_Wilson의_루트10배_안팎이다"),
    ("M4 percentile 상하한 뒤바꿈", "    return (lo, hi)", "    return (hi, lo)",
     "test_변이4_하한이_상한보다_크지_않다"),
    ("M5 짝 깨기", "        b = [pairs[i][1] for i in idx]",
     "        b = [pairs[rng.randrange(m)][1] for _ in range(m)]",
     "test_변이5_짝지은_차이는_상수차이_자료에서_폭이_거의_0이다"),
    ("M6 이름 정규화 누락", '        k = key_of(r, gen_name).split("|", 1)[1]',
     '        k = key_of(r, None).split("|", 1)[1]',
     "test_변이6_제너레이터_이름을_정규화해야_두_팔이_짝지어진다"),
    ("M7 B=10", "B_DEFAULT = 10_000", "B_DEFAULT = 10",
     "test_변이7_B가_충분하면_다른_seed에서도_경계가_거의_같다"),
]


def main():
    with tempfile.TemporaryDirectory(prefix="cluster-mutations-") as tmp:
        root = pathlib.Path(tmp)
        for name in ("scripts/cluster_ci.py", "scripts/matched_baseline.py", "tests/test_cluster_ci.py"):
            dest = root / name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        target = root / "scripts/cluster_ci.py"
        original = target.read_text()

        def run(node=""):
            report = root / "pytest.xml"
            report.unlink(missing_ok=True)
            p = subprocess.run([sys.executable, "-B", "-m", "pytest",
                                "tests/test_cluster_ci.py" + node, "-q", "--tb=short",
                                f"--junitxml={report}"], cwd=root, capture_output=True, text=True)
            if not report.exists():
                raise RuntimeError(p.stdout + p.stderr)
            return p, ET.parse(report).getroot()

        p, report = run()
        if p.returncode != 0:
            print(p.stdout + p.stderr)
            return 1
        print(f"기준선: {len(report.findall('.//testcase'))} passed", flush=True)
        for name, old, new, test in MUTATIONS:
            if original.count(old) != 1:
                raise RuntimeError(f"{name}: 앵커가 유일하지 않음")
            mutated = original.replace(old, new)
            compile(mutated, str(target), "exec")
            target.write_text(mutated)
            p, report = run("::" + test)
            failures = report.findall(".//failure")
            caught = (p.returncode == 1 and len(failures) == 1
                      and not report.findall(".//error")
                      and ("AssertionError" in failures[0].get("message", "")
                           or failures[0].get("message", "").startswith("assert ")))
            print(f"{name}: {'검출' if caught else '검증 실패'} — {test}", flush=True)
            if not caught:
                print(p.stdout + p.stderr)
                return 1
        print("7/7 검출. 원본 파일 무수정.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
