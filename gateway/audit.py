"""감사 로그 — 요청 1건 = JSONL 1줄.

편의 기능이 아니라 평가 인프라다. EVAL 4절의 p50/p95/p99 지연과
EVAL 3.3의 `blocked` 플래그 자동 판정이 모두 이 파일을 읽는다.

원칙: 요청 본문 원문은 남기지 않는다(2026-08-07 결정).
바이트 수와 SHA-256 앞 12자리만 기록한다. 개인정보 유출을 막는
게이트웨이가 자기 로그에 평문을 쌓으면 유출 지점을 옮긴 것뿐이다.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def digest(body: bytes) -> str:
    """본문 지문. 원문 복원은 불가능하지만 '같은 요청인지'는 비교할 수 있다."""
    return hashlib.sha256(body).hexdigest()[:12]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AuditLog:
    """append-only JSONL. 줄 단위로 flush하므로 서버가 죽어도 직전까지 남는다."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = self.path.open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:      # uvicorn 워커가 여러 개여도 줄이 섞이지 않게
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()
