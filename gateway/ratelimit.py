"""클라이언트별 분당 요청 상한(D-107 E). 메모리의 미끄럼 창 — 워커 1개라 충분하다.

키는 인증된 클라이언트 이름, 무인증이면 IP. 넘으면 429 + retry-after. 상류·검사기를 부르지 않는다.
# ponytail: 프로세스 메모리 창. 워커를 늘리거나 여러 인스턴스를 두면 Redis 같은 공유 저장소로 옮긴다.
"""
from __future__ import annotations

import math
import time
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """(허용 여부, 거부 시 retry-after 초). 허용하면 이번 요청을 센다."""
        if not self.enabled:
            return True, 0
        now = time.monotonic() if now is None else now
        window = self._hits.setdefault(key, deque())
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) >= self.per_minute:
            return False, max(1, math.ceil(60.0 - (now - window[0])))
        window.append(now)
        if len(self._hits) > 10_000:                      # 오래된 키를 버린다 — 무한히 쌓이면 그 자체가 취약점이다
            for k in [k for k, w in self._hits.items() if not w or now - w[-1] >= 60.0]:
                del self._hits[k]
        return True, 0
