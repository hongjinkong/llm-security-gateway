"""D-069: CI의 pytest junit 결과를 판정한다.

`pytest -q`의 종료 코드 0은 "실패·오류가 없다"만 말한다. 새 체크아웃에서 파일이 없어
테스트가 건너뛰어져도 0이다. 이 판정기는 D-069 A4를 판정한다.

    python3 scripts/ci_junit_check.py junit.xml

종료 코드 (D-064와 같은 세 갈래):
    0  합격   — 테스트 >0, 실패·오류·skip(xfail 포함) 0, 요약 속성과 개별 결과 일치
    1  불합격 — 실패·오류·skip이 있다
    2  무효   — 파일 없음·파싱 실패·junit 아님·요약 속성 누락·테스트 0개·
                요약 속성과 개별 결과 불일치. **자료의 부재는 결과가 아니다.**

표준 라이브러리만 쓴다. README 설치 절차가 실패한 뒤에도 돌 수 있어야 하기 때문이다.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ATTRS = ("tests", "failures", "errors", "skipped")


class Invalid(Exception):
    """판정할 자료가 없거나 믿을 수 없다."""


def load_suites(path: Path) -> list[ET.Element]:
    if not path.is_file():
        raise Invalid(f"junit 파일이 없다: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise Invalid(f"junit 파싱 실패: {e}") from e
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        suites = root.findall("testsuite")
        if not suites:
            raise Invalid("<testsuites> 안에 <testsuite>가 없다")
        return suites
    raise Invalid(f"junit 뿌리 요소가 아니다: <{root.tag}>")


def declared(suite: ET.Element) -> dict[str, int]:
    """<testsuite>의 요약 속성. 하나라도 없거나 정수가 아니면 무효."""
    out = {}
    for a in ATTRS:
        v = suite.get(a)
        if v is None:
            raise Invalid(f"<testsuite>에 {a} 속성이 없다")
        try:
            out[a] = int(v)
        except ValueError as e:
            raise Invalid(f"<testsuite> {a}={v!r}는 정수가 아니다") from e
    return out


def observed(suite: ET.Element) -> dict[str, int]:
    """개별 <testcase>를 직접 센 값. pytest는 teardown 오류가 겹친 테스트를
    <testcase> 하나에 <failure>와 <error>를 함께 적으므로 자식 요소 단위로 센다."""
    cases = suite.findall("testcase")
    return {
        "tests": len(cases),
        "failures": sum(len(c.findall("failure")) for c in cases),
        "errors": sum(len(c.findall("error")) for c in cases),
        "skipped": sum(len(c.findall("skipped")) for c in cases),
    }


def judge(path: Path) -> tuple[int, dict[str, int] | None, list[str]]:
    """(종료 코드, 집계, 사유)."""
    try:
        suites = load_suites(path)
        total = dict.fromkeys(ATTRS, 0)
        for s in suites:
            d, o = declared(s), observed(s)
            if d != o:
                raise Invalid(f"요약 속성 {d}과 개별 결과 {o}가 다르다 — 어느 쪽도 믿을 수 없다")
            for a in ATTRS:
                total[a] += o[a]
    except Invalid as e:
        return 2, None, [str(e)]

    total["passed"] = total["tests"] - len(_problem_cases(suites))
    if total["tests"] == 0:
        return 2, total, ["테스트가 0개다 — 검사하지 않은 것은 통과가 아니다"]
    reasons = [f"{a} {total[a]}건" for a in ("failures", "errors", "skipped") if total[a]]
    return (1 if reasons else 0), total, reasons


def _problem_cases(suites: list[ET.Element]) -> list[ET.Element]:
    return [c for s in suites for c in s.findall("testcase")
            if c.find("failure") is not None or c.find("error") is not None
            or c.find("skipped") is not None]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("사용법: python3 scripts/ci_junit_check.py junit.xml", file=sys.stderr)
        return 2
    code, total, reasons = judge(Path(argv[1]))
    if total is not None:
        print("junit: tests={tests} passed={passed} failures={failures} "
              "errors={errors} skipped={skipped}".format(**total))
    verdict = {0: "합격", 1: "불합격", 2: "무효"}[code]
    print(f"판정: {verdict}" + (" — " + "; ".join(reasons) if reasons else ""))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
