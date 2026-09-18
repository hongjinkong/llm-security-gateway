"""실행 중인 코드의 지문.

왜 필요한가 (2026-08-07에 실제로 당한 사고):
  `git pull`로 소스는 최신이 됐는데 `docker compose build`를 빠뜨려서,
  컨테이너 안에서는 **옛 코드**가 돌고 있었다. 겉으로는 아무 차이가 없어서
  28분짜리 측정을 마친 뒤에야 이상한 숫자 하나로 발견했다.
  발견 못 했다면 옛 코드로 잰 결과를 최신 코드의 성능으로 리포트할 뻔했다.

그래서 게이트웨이가 자기가 실행 중인 소스의 해시를 스스로 보고하게 한다.
저장소에서 같은 방식으로 계산한 값과 비교하면 어긋남을 즉시 알 수 있다.
git이 필요 없으므로 컨테이너 안에서도 동작한다.
"""
from __future__ import annotations

import hashlib
import pathlib

PKG = pathlib.Path(__file__).resolve().parent


def code_fingerprint(pkg_dir: pathlib.Path | None = None) -> str:
    """gateway 패키지의 모든 .py 파일 내용을 해시한다. 앞 12자리를 쓴다."""
    root = pkg_dir or PKG
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        h.update(path.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]


def canary_fingerprint(token: str) -> str:
    """카나리 값의 지문. **값이 아니라** sha256 앞 8자리 (D-058 / CANARY_DESIGN 3-2).

    왜 여기 있는가: `.env` · 게이트웨이 health · `eval/setup_target.py` 세 곳이
    **같은 계산식**을 써야 대조가 성립한다. 세 번 따로 구현하면 D-057의
    *"둘 다 같은 파일을 읽으니 같겠지"*가 그대로 재발한다.

    `gateway/detectors/canary.py`가 아니라 이 파일에 두는 이유: `setup_target.py`가
    import해야 하는데, canary.py를 import하면 `base.py`의 `StrEnum`(3.11+)이 딸려온다.
    setup_target은 학원 PC에서 도는 스크립트다. 이 파일은 hashlib과 pathlib만 쓴다.

    **한계를 적어둔다.** 카나리 값의 공간은 8자리 hex = 2^32라, 지문을 아는 사람은
    전수 탐색으로 원본을 복원할 수 있다. 노트북에서 몇 분이다.
    **지문은 값을 가리는 장치가 아니라 대조하는 장치다.**

    지금은 무해하다 — D-058 결정 (4)가 *"관측형에서는 값 공개가 무해하다"*고 이미
    판단했다. 응답을 안 바꾸므로 공격자가 값을 알아도 로그 한 줄이 더 찍힐 뿐이고,
    살아 있는 값은 이미 커밋된 `results/*.jsonl` 여러 건에 들어 있다.
    **D-059가 차단형을 여는 순간 이 판단이 뒤집힌다** — 그때 공개된 값은 공격자
    통제 하의 차단 트리거가 되고 `/__gateway/health`가 그 통로가 된다.
    차단형 승격 시 이 함수의 노출 지점을 함께 재검토할 것.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


if __name__ == "__main__":
    print(code_fingerprint())
