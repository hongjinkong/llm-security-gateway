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


if __name__ == "__main__":
    print(code_fingerprint())
