"""`python -m gateway keygen [--hash]` — 클라이언트 키 하나를 찍는다(D-107 A). 그 밖의 인자는 사용법을 낸다.

`--hash`면 둘째 줄에 설정 파일 `[[clients]]`에 넣을 `key_sha256 = "…"`을 낸다(D-119) — 키(첫 줄)는 클라이언트에만 주고 파일에는 해시만 둔다.
"""
from __future__ import annotations

import sys

from gateway.auth import keygen
from gateway.settings import key_hash

if __name__ == "__main__":
    if sys.argv[1:] in (["keygen"], ["keygen", "--hash"]):
        key = keygen()
        print(key)
        if sys.argv[2:]:
            print(f'key_sha256 = "{key_hash(key)}"')
    else:
        print("사용법: python -m gateway keygen [--hash]", file=sys.stderr)
        raise SystemExit(2)
