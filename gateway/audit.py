"""감사 로그 — 요청 1건 = JSONL 1줄.

편의 기능이 아니라 평가 인프라다. EVAL 4절의 p50/p95/p99 지연과
EVAL 3.3의 `blocked` 플래그 자동 판정이 모두 이 파일을 읽는다.

원칙: 요청 본문 원문은 남기지 않는다(2026-08-07 결정).
바이트 수와 SHA-256 앞 12자리만 기록한다. 개인정보 유출을 막는
게이트웨이가 자기 로그에 평문을 쌓으면 유출 지점을 옮긴 것뿐이다.

D-107 E: 경로가 `-`면 stdout(컨테이너 관례), 파일이면 크기 회전(stdlib RotatingFileHandler — max_bytes·backups).
줄마다 flush는 그대로다(핸들러의 emit이 flush한다). `on_write` 훅으로 지표가 같은 레코드를 센다 — 집계가 한 곳이다.
D-118: 감사 줄의 모양(`record`)도 여기에 둔다 — main.py에서 옮겼다.
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
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from gateway.chain import ChainResult, Step

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


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


def record(request: Request, response: Response | None,
           total_ms: float, error: str | None, res_bytes: int | None = None) -> dict:
    """감사 로그 한 줄. 예외로 끝난 요청도 **같은 모양으로** 남긴다.

    모양이 갈리면 집계 도구가 한쪽을 조용히 빠뜨린다 — 그게 이 프로젝트가
    FPR 집계기에서 이미 겪은 실패다(D-064).
    `res_bytes`는 스트리밍 응답처럼 content-length가 없을 때 호출자가 센 값이다(D-106).
    """
    state = request.state
    upstream_ms = getattr(state, "upstream_ms", None)
    return {
        "ts": utcnow(),
        "request_id": state.request_id,
        "method": request.method,
        "path": request.url.path,
        # ★ 2026-09-22: 예전에는 쿼리 문자열을 원문 그대로 남겼다. 본문과 Authorization
        # 헤더는 안 남기면서 URL은 보호 밖이었다 — URL에 개인정보나 토큰이 실리면 그대로
        # 기록된다. 본문에 이미 쓰는 규칙("원문은 남기지 않는다, 크기와 지문만")을
        # URL에도 적용하되, **키 이름은 남긴다**: "URL에 token이 실려 왔다"는 사실은
        # 운영에 필요하고, 위험한 것은 값이다.
        "query_keys": query_keys(request.url.query),
        "query_bytes": len(request.url.query),
        # 예외로 끝난 요청은 상위 미들웨어가 500으로 바꾼다. 그 사실을 그대로 적는다.
        "status": response.status_code if response is not None else 500,
        "error": error or getattr(state, "upstream_error", None),
        # EVAL 4절: 종단 지연 / 타겟 호출 / 게이트웨이 내부 처리를 분리한다.
        "total_ms": round(total_ms, 2),
        "upstream_ms": None if upstream_ms is None else round(upstream_ms, 2),
        "gateway_ms": round(total_ms - (upstream_ms or 0.0), 2),
        # 본문 원문은 남기지 않는다. 크기와 지문만.
        "req_bytes": getattr(state, "req_bytes", None),
        "req_sha256_12": getattr(state, "req_digest", None),
        "res_bytes": res_bytes if res_bytes is not None else (
            _int_or_none(response.headers.get("content-length")) if response is not None else None),
        "blocked": getattr(state, "blocked", False),
        "client": getattr(state, "client", None),          # 키 이름(D-107 A). 예전에는 IP였다 — 이제 `ip`
        "ip": request.client.host if request.client else None,
        "api": getattr(state, "api", None),                # chat | messages | responses | models | null (D-107 C·D-109)
        "model": getattr(state, "model", None),            # 요청의 model(D-120)
        "usage": getattr(state, "usage", None),            # {input, output, cache_read, cache_write} 토큰 — 상류가 준 것(D-120)
        "policy": getattr(state, "policy", None),          # 정책 이름(D-119)
        "config": getattr(getattr(request.app.state, "settings", None), "config_version", None),   # 설정 파일 버전(D-119)
        "upstream_request_id": getattr(state, "upstream_request_id", None),
        **pii_fields(getattr(state, "response_steps", [])),
        **_chain_fields(getattr(state, "chain_result", None)),
        "response_detectors": [s.as_dict() for s in getattr(state, "response_steps", [])],
    }


def pii_fields(steps: list[Step]) -> dict:
    """복원 가시화(D-113): 발급·복원·의심 잔여를 감사 줄 맨 위에 둔다 — 집계가 response_detectors를 뒤지지 않게.
    `pii_new`(D-120): 응답에 새로 나온 PII·비밀 수(우리가 가린 원문·발급한 대체값이 아닌 것). detect 모드도 센다."""
    meta = next((s.meta for s in steps if s.detector in ("pii_mask", "pii")), {})
    return {"pii_issued": meta.get("issued", 0), "pii_restored": meta.get("restored", 0), "pii_suspect": meta.get("suspect", 0),
            "pii_new": meta.get("new", 0)}


def _int_or_none(v: str | None) -> int | None:
    return int(v) if v is not None and v.isdigit() else None


def query_keys(query: str) -> list[str]:
    """쿼리 파라미터의 **이름만** 정렬해 돌려준다. 값은 담지 않는다.

    `parse_qsl`을 쓰지 않는 이유: 값이 잠깐이라도 중간 자료구조에 들어가는 경로를
    만들지 않는다. 여기서는 '='의 앞부분만 본다. 중복 이름은 한 번만 센다.
    """
    keys = set()
    for part in query.split("&"):
        if not part:
            continue
        name = unquote(part.split("=", 1)[0])
        if name:
            keys.add(name)
    return sorted(keys)


def _chain_fields(result: ChainResult | None) -> dict:
    """검사기 체인 실행 내역. EVAL 4절이 요구하는 단계별 소요 시간을 남긴다."""
    if result is None:
        return {"chain_ms": None, "detectors": [], "blocked_by": None, "transformed": False}
    return {
        "chain_ms": result.chain_ms,
        "detectors": [s.as_dict() for s in result.steps],
        "blocked_by": result.blocked_by,
        "transformed": result.transformed,
    }
