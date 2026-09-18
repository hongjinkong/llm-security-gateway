#!/usr/bin/env python3
"""변이 검사 — `tests/test_canary.py`가 실제로 무언가를 지키는지 확인한다.

**왜 필요한가.** 테스트가 통과했다는 것은 그 테스트가 옳은 것을 시험했다는 뜻이
아니다(D-055). 화재경보기가 "정상"이라고 표시하는 것과 불이 났을 때 울리는 것은
다른 일이고, 후자는 불을 질러 봐야 안다. 이 스크립트가 불을 지른다 —
`gateway/detectors/canary.py`를 일부러 망가뜨리고, 테스트가 그걸 잡는지 본다.

**변이가 아무것도 안 깨뜨리면 그 테스트는 아무것도 안 지키는 것이다.**

손으로 하지 않는 이유: 7회 반복이고 되돌리기를 한 번 빠뜨리면 **변이된 코드가
커밋된다.** 이 저장소에서 가장 나쁜 실패 계열이다(옛 코드로 측정, 2026-08-07).
여기서는 원본을 메모리에 들고 `try/finally`로 무조건 원복하고, 끝에
`git diff --stat`을 찍어 트리가 깨끗한지 눈으로 확인시킨다.

사용:
    python3 scripts/mutate_canary.py

측정이 아니다. Ollama도 GPU도 타겟 앱도 쓰지 않는다.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "gateway" / "detectors" / "canary.py"
TESTS = "tests/test_canary.py"

# 변이의 앵커. 원본에 정확히 한 번 나와야 한다 — 안 나오거나 여러 번 나오면
# 소스가 바뀐 것이고, 조용히 넘어가면 "변이를 걸었다고 믿었는데 안 걸린" 상태로
# 전부 통과가 나온다. 그 통과는 거짓말이다. 그래서 앵커 검사부터 한다.
COUNTS = "        counts = {kind: text.count(token) for kind, token in self._tokens.items()}"
RETURN = "        return text, counts"
MISSING = "        missing = [k for k, v in self._tokens.items() if not v]"
COLLIDED = "        collided = [ks for ks in by_value.values() if len(ks) > 1]"
POSITION = "    if names[-1] != NAME:"

MUTATIONS = [
    {
        "id": "M1",
        "설계": "변이 1 — 관측형은 응답을 바꾸지 않는다",
        "무엇": "on_response가 카나리를 지우고 돌려준다",
        "old": RETURN,
        "new": ("        for _t in self._tokens.values():\n"
                "            text = text.replace(_t, \"\")\n"
                "        return text, counts"),
    },
    {
        "id": "M2",
        "설계": "변이 2 — 값이 없으면 기동 실패",
        "무엇": "prepare()의 값 존재 검사를 없앤다",
        "old": MISSING,
        "new": "        missing = []",
    },
    {
        "id": "M3",
        "설계": "변이 3 — meta에 토큰 값이 없다",
        "무엇": "meta에 검출된 토큰 문자열을 함께 담는다",
        "old": COUNTS,
        "new": COUNTS + "\n        counts[\"sample\"] = next(iter(self._tokens.values()))",
    },
    {
        "id": "M4",
        "설계": "변이 4 — 세 종류를 구분한다",
        "무엇": "종류를 안 나누고 합계를 세 칸에 똑같이 넣는다",
        "old": COUNTS,
        "new": ("        _total = sum(text.count(t) for t in self._tokens.values())\n"
                "        counts = {kind: _total for kind in self._tokens}"),
    },
    {
        "id": "M5",
        "설계": "변이 5 — 소스에 카나리 리터럴이 없다",
        "무엇": "카나리 형식 접두사를 상수로 박는다",
        # 여기서는 접두사를 **끊지 않고** 그대로 쓴다. `"WS-" "2026-"`처럼 쪼개면
        # 실행 시 값은 같지만 소스 텍스트에는 그 문자열이 없어서 변이가 안 걸린다.
        # 이 스크립트는 scripts/ 에 있고 리터럴 검사는 gateway/ 만 훑으므로 안전하다.
        "append": "\n\nLEGACY_CANARY_PREFIX = \"WS-2026-\"\n",
    },
    {
        "id": "M6",
        "설계": "보강 (2026-08-21) — 체인 위치 강제",
        "무엇": "위치 검사를 무력화한다",
        "old": POSITION,
        "new": "    if False:",
    },
    {
        "id": "M7",
        "설계": "보강 (2026-08-21) — 중복값 검사",
        "무엇": "세 값이 겹쳐도 통과시킨다",
        "old": COLLIDED,
        "new": "        collided = []",
    },
]


def run_tests() -> tuple[bool, str, list[str]]:
    """돌려주는 것: (전부 통과했나, 요약 줄, 실패한 테스트 이름들)."""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS, "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True)
    out = p.stdout + p.stderr
    summary = ""
    failed: list[str] = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(("FAILED ", "ERROR ")):
            name = s.split(" ", 1)[1].split(" - ")[0]
            failed.append(name.split("::", 1)[-1])
        if ("passed" in s or "failed" in s or "error" in s) and (
                "=" in s or s.endswith("s") or "in " in s):
            summary = s
    return p.returncode == 0, summary, failed


def apply_mutation(original: str, m: dict) -> str:
    if "append" in m:
        return original + m["append"]
    n = original.count(m["old"])
    if n != 1:
        raise SystemExit(
            f"{m['id']}: 앵커가 원본에 {n}번 나온다 (1번이어야 한다).\n"
            f"  앵커: {m['old']!r}\n"
            f"  → canary.py가 바뀌었다. 앵커를 고치기 전에는 이 스크립트를 믿지 말 것.\n"
            f"     앵커가 안 맞는데 그냥 돌리면 '변이를 걸었다고 믿었는데 안 걸린' 상태로\n"
            f"     전부 통과가 나오고, 그 통과는 거짓말이다.")
    return original.replace(m["old"], m["new"])


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")

    print("=" * 74)
    print("변이 검사 — tests/test_canary.py")
    print(f"대상: {TARGET.relative_to(ROOT)}")
    print("=" * 74)

    # 0) 양성대조. 변이 없이 먼저 통과해야 한다. 여기서 실패하면 아래 결과는
    #    전부 의미가 없다 — "변이 때문에 실패했다"를 주장할 수 없다.
    print("\n[기준선] 변이 없이 실행")
    ok, summary, _ = run_tests()
    print(f"  {summary}")
    if not ok:
        print("  ❌ 변이 전부터 실패한다. 변이 검사를 돌릴 상태가 아니다.")
        return 1
    print("  ✅ 기준선 통과")

    results = []
    try:
        for m in MUTATIONS:
            print(f"\n[{m['id']}] {m['설계']}")
            print(f"  변이: {m['무엇']}")
            TARGET.write_text(apply_mutation(original, m), encoding="utf-8")
            ok, summary, failed = run_tests()
            caught = not ok
            results.append((m, caught, failed))
            print(f"  {summary}")
            if caught:
                print(f"  ✅ 잡혔다 ({len(failed)}개 실패)")
                for name in failed[:6]:
                    print(f"       - {name}")
                if len(failed) > 6:
                    print(f"       - ... 외 {len(failed) - 6}개")
            else:
                print("  ❌ **안 잡혔다.** 이 성질은 테스트가 지키지 않고 있다")
    finally:
        TARGET.write_text(original, encoding="utf-8")
        print(f"\n원복: {TARGET.relative_to(ROOT)}")

    print("\n" + "=" * 74)
    missed = [m["id"] for m, caught, _ in results if not caught]
    for m, caught, failed in results:
        mark = "✅" if caught else "❌"
        print(f"  {mark} {m['id']}  {m['설계']:<42} {len(failed)}개 실패")
    print("=" * 74)

    # 원복이 실제로 됐는지 눈으로 확인시킨다. "되돌렸다고 믿는 것"과
    # "되돌아간 것"은 다르다 — 이 저장소가 반복해서 밟은 자리다.
    print("\n[원복 확인] git diff --stat")
    d = subprocess.run(["git", "--no-optional-locks", "diff", "--stat",
                        "--", str(TARGET.relative_to(ROOT))],
                       cwd=ROOT, capture_output=True, text=True)
    print((d.stdout or "  (변경 없음)").rstrip())

    if missed:
        print(f"\n❌ 안 잡힌 변이: {', '.join(missed)}")
        print("   해당 성질은 테스트가 지키고 있지 않다. 테스트를 보강할 것.")
        return 1
    print(f"\n✅ 변이 {len(results)}종 전부 잡혔다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
