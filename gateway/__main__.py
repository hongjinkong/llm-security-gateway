"""`python -m gateway keygen` — 클라이언트 키 하나를 찍는다(D-107 A). 그 밖의 인자는 사용법을 낸다."""
from __future__ import annotations

import sys

from gateway.auth import keygen

if __name__ == "__main__":
    if sys.argv[1:] == ["keygen"]:
        print(keygen())
    else:
        print("사용법: python -m gateway keygen", file=sys.stderr)
        raise SystemExit(2)
