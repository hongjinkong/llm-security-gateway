"""감사 로그 — 요청 1건 = JSONL 1줄.

편의 기능이 아니라 평가 인프라다. EVAL 4절의 p50/p95/p99 지연과
EVAL 3.3의 `blocked` 플래그 자동 판정이 모두 이 파일을 읽는다.

원칙: 요청 본문 원문은 남기지 않는다(2026-08-07 결정).
바이트 수와 SHA-256 앞 12자리만 기록한다. 개인정보 유출을 막는
게이트웨이가 자기 로그에 평문을 쌓으면 유출 지점을 옮긴 것뿐이다.

D-107 E: 경로가 `-`면 stdout(컨테이너 관례), 파일이면 크기 회전(stdlib RotatingFileHandler — max_bytes·backups).
줄마다 flush는 그대로다(핸들러의 emit이 flush한다). `on_write` 훅으로 지표가 같은 레코드를 센다 — 집계가 한 곳이다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import sys
from collections.abc import Callable
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

    def __init__(self, path: str | Path, max_bytes: int = 100 * 1024 * 1024, backups: int = 5,
                 on_write: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.path = None if str(path) in ("-", "stdout") else Path(path)
        self._on_write = on_write
        self._logger = logging.Logger(f"gateway.audit.{id(self)}")     # 루트에 매달지 않는다 — 다른 핸들러로 새지 않게
        self._logger.propagate = False
        if self.path is None:
            self._handler: logging.Handler = logging.StreamHandler(sys.stdout)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handler = logging.handlers.RotatingFileHandler(
                self.path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(self._handler)

    def write(self, record: dict[str, Any]) -> None:
        self._logger.info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))   # 핸들러 lock + flush
        if self._on_write is not None:
            self._on_write(record)

    def close(self) -> None:
        self._handler.close()
