"""운영 지표 — `/__gateway/metrics`, Prometheus 텍스트 형식, 의존성 없음(D-107 E).

감사 레코드 하나에서 전부 센다(`AuditLog.on_write`). 프로세스 메모리의 카운터라 워커·재시작 단위다.
  gateway_requests_total{api,status,blocked}   요청 수
  gateway_outcomes_total{outcome,reason}       처리 결과 7가지와 사유(D-124, `outcome`)
  gateway_injection_hits_total{mode}           인젝션 룰 적중(observe는 would_block, block은 차단·가림)
  gateway_pii_masked_total{kind}               실제로 가린 건수(종류별, pii_mask만 — D-124 전에는 detect 정책의 찾은 수가 섞였다)
  gateway_pii_unmasked_total{kind}             찾았지만 가리지 않은 건수(detect 정책 + 기본 감사만 종류, D-124)
  gateway_pii_restored_total / gateway_pii_residual_total   복원 건수 / 복원 뒤 남은 대체값 수
  gateway_pii_suspect_total                    의심 잔여 — 남은 대체값 + 대체값의 식별 조각(끝 4자리·로컬파트)만 나타난 경우(D-113)
  gateway_pii_new_total                        응답에 새로 나온 PII·비밀(우리가 가린 원문·발급한 대체값이 아닌 것, D-120) — 가리지 않는다
  gateway_upstream_ms_sum/_count, gateway_total_ms_sum/_count   지연 합·횟수(평균은 나눠서)
  gateway_vault_sessions{policy}               진행 중인 대체값 세션(게이지, D-122) — 정책·워커당 2,000이면 503 gateway_busy
  gateway_upstream_connections_in_use{upstream} 빌려 간 상류 연결(게이지, D-122) — GATEWAY_MAX_CONNECTIONS면 기다리다 503 upstream_busy.
                                               주소가 같고 timeout이 다른 풀이 있으면 가장 바쁜 풀의 값(D-124 — 상한이 풀마다라서)
D-124: 같은 레코드에서 결과를 분류하고 최근 200줄(`row` — 원문·가짜 값·위치·IP 없음)을 링에 담는다. `/__gateway/stats`와 대시보드가 `snapshot`을 읽는다.
"""
from __future__ import annotations

import os
import threading
from collections import Counter, deque
from typing import Any

import httpx

from gateway.audit import utcnow

# 게이트웨이가 상류에 보내지 않고 거절한 요청의 감사 `error` 코드(D-124). 새 코드를 만들면 여기나 UPSTREAM_ERRORS에 넣는다 — 테스트가 소스를 훑어 지킨다.
REJECTED = frozenset({"unauthorized", "rate_limited", "request_too_large", "too_many_findings", "model_not_allowed",
                      "invalid_json", "invalid_messages", "invalid_request", "invalid_stream", "not_found",
                      "gateway_busy", "upstream_busy"})
# 상류 호출 실패 — relay가 감사 `error`에 예외 이름을 적는다. 스트림 도중이면 상태가 200이다(이미 머리를 보냈다).
# upstream_stream_error: 상류가 머리(200) 뒤 스트림 안에 보낸 오류 이벤트(Anthropic `event: error` overloaded_error 등, D-124).
UPSTREAM_ERRORS = frozenset({c.__name__ for c in vars(httpx).values()
                             if isinstance(c, type) and issubclass(c, httpx.RequestError)} | {"response_too_large", "upstream_stream_error"})
OUTCOMES = ("masked", "passed", "observed", "blocked", "rejected", "upstream_error", "failed")
RECENT = 200
ROW_KEYS = ("ts", "request_id", "client", "policy", "api", "model", "status", "outcome", "reason", "gateway_ms", "upstream_ms",
            "masked", "unmasked", "masked_turns", "rules", "issued", "restored", "suspect", "new")


def _steps(rec: dict) -> list[dict]:
    return [d for d in rec.get("detectors") or [] if isinstance(d, dict)]


def _counts(value: Any) -> Counter:
    """{종류: 수}만 받는다. 다른 모양은 버린다 — Counter.update는 문자열을 글자로 세고, 빈 카운터에는 값을 검사 없이 넣어 다음 레코드부터 계속 터진다."""
    if not isinstance(value, dict):
        return Counter()
    return Counter({k: v for k, v in value.items() if isinstance(k, str) and type(v) is int})


def _kinds(rec: dict) -> tuple[Counter, Counter]:
    """(가린 것, 가리지 않은 것) 종류별 수. pii_mask의 `pii`는 가린 것만 센다(D-116) — 남은 탐지는 `unmasked`. detect 정책(`pii`)은 전부 가리지 않은 것."""
    masked: Counter = Counter()
    unmasked: Counter = Counter()
    for d in _steps(rec):
        if d.get("detector") == "pii_mask":
            masked.update(_counts(d.get("pii")))
            unmasked.update(_counts(d.get("unmasked")))
        elif d.get("detector") == "pii":
            unmasked.update(_counts(d.get("pii")))
    return masked, unmasked


def outcome(rec: dict) -> tuple[str, str]:
    """(결과, 사유) — 위에서부터 처음 맞는 것(D-124 §2-3). 사유는 공백 없는 코드다."""
    error, status = rec.get("error"), rec.get("status") or 0
    if rec.get("blocked"):
        return "blocked", str(rec.get("blocked_by") or "blocked")
    if error in REJECTED:
        return "rejected", error
    if error in UPSTREAM_ERRORS:
        return "upstream_error", error
    if error:
        return "failed", str(error)
    if status >= 400:
        return ("upstream_error", f"upstream_{status}") if rec.get("upstream_ms") is not None else ("rejected", f"http_{status}")
    steps = _steps(rec)
    masked, unmasked = _kinds(rec)
    if rec.get("transformed"):
        if masked:
            return "masked", "pii_mask"
        if any(d.get("masked_turns") for d in steps):
            return "masked", "masked_turns"
        return "masked", next((str(d.get("detector")) for d in steps if d.get("action") == "transform"), "transformed")
    if any(d.get("would_block") for d in steps):
        return "observed", "injection_observe"
    if unmasked:
        return "observed", "unmasked"
    return "passed", "none"


def _cut(value: Any, n: int) -> Any:
    return value[:n] if isinstance(value, str) else value


def row(rec: dict, result: tuple[str, str]) -> dict:
    """최근 요청 한 줄(D-124) — `ROW_KEYS`만. 원문·가짜 값은 감사 레코드에 처음부터 없고, 위치·IP·경로·쿼리 키·usage도 싣지 않는다.
    클라이언트가 정하는 긴 값(model, 룰 어휘가 붙잡은 공백 묶음)은 자른다 — 200줄이 0.5MB를 넘지 않게."""
    steps = _steps(rec)
    masked, unmasked = _kinds(rec)
    rules = [h for d in steps for h in d.get("rules") or [] if isinstance(h, dict)][:5]
    return {
        "ts": rec.get("ts"), "request_id": rec.get("request_id"), "client": rec.get("client"), "policy": rec.get("policy"),
        "api": rec.get("api"), "model": _cut(rec.get("model"), 64), "status": rec.get("status"),
        "outcome": result[0], "reason": result[1], "gateway_ms": rec.get("gateway_ms"), "upstream_ms": rec.get("upstream_ms"),
        "masked": dict(masked), "unmasked": dict(unmasked),
        "masked_turns": sum(d.get("masked_turns") or 0 for d in steps),
        "rules": [{"rule": _cut(h.get("rule"), 40), "trigger": _cut(h.get("trigger"), 40), "object": _cut(h.get("object"), 40)} for h in rules],
        "issued": rec.get("pii_issued", 0), "restored": rec.get("pii_restored", 0),
        "suspect": rec.get("pii_suspect", 0), "new": rec.get("pii_new", 0),
    }


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Counter = Counter()
        self.injection: Counter = Counter()
        self.masked: Counter = Counter()
        self.unmasked: Counter = Counter()
        self.outcomes: Counter = Counter()
        # ponytail: 링은 하나다 — 부하 중에는 차단·거절 줄도 몇 초 안에 밀려난다. 필요해지면 passed·masked가 아닌 줄만 담는 두 번째 링을 둔다.
        self.recent: deque[dict] = deque(maxlen=RECENT)
        self.started = utcnow()                # 감사 줄 ts와 같은 형식. 이미지에서는 uvicorn이 PID 1이라 파드는 started로 가른다
        self.pid = os.getpid()
        self.restored = self.residual = self.suspect = self.new = 0
        self.upstream_ms = self.total_ms = 0.0
        self.upstream_n = self.total_n = 0

    def observe(self, rec: dict) -> None:
        """감사 레코드 하나를 센다. 예외를 올리지 않는다(D-124) — AuditLog.write와 미들웨어가 이 호출을 try 없이 하므로 여기서 터지면 그 요청이 500이 된다.
        실패하면 그 레코드의 남은 집계와 줄을 버린다(감사 줄은 이미 써졌다)."""
        with self._lock:
            try:
                self.requests[(rec.get("api") or "other", rec.get("status"), bool(rec.get("blocked")))] += 1
                for d in _steps(rec):
                    name = str(d.get("detector", ""))
                    if name.startswith("injection") and (d.get("rules") or d.get("would_block")):
                        self.injection["observe" if name == "injection_observe" else "block"] += 1
                masked, unmasked = _kinds(rec)
                self.masked.update(masked)
                self.unmasked.update(unmasked)
                for d in rec.get("response_detectors") or []:
                    if d.get("detector") in ("pii_mask", "pii"):
                        self.restored += d.get("restored") or 0
                        self.residual += d.get("residual_tokens") or 0
                        self.suspect += d.get("suspect") or 0
                        self.new += d.get("new") or 0
                if rec.get("total_ms") is not None:
                    self.total_ms += rec["total_ms"]
                    self.total_n += 1
                if rec.get("upstream_ms") is not None:
                    self.upstream_ms += rec["upstream_ms"]
                    self.upstream_n += 1
                result = outcome(rec)
                line = row(rec, result)
                self.outcomes[result] += 1
                self.recent.appendleft(line)
            except Exception:
                pass

    def snapshot(self, vault_sessions: dict[str, int], upstream_in_use: dict[str, int], max_connections: int) -> dict:
        """`/__gateway/stats`의 본문(D-124). 락 안에서 복사한다. 평균은 횟수가 0이면 null — NaN이면 JSONResponse가 500을 낸다."""
        with self._lock:
            status: Counter = Counter()
            for (_, code, _), n in self.requests.items():
                status[str(code)] += n
            outcomes = dict.fromkeys(OUTCOMES, 0)
            for (result, _), n in self.outcomes.items():
                outcomes[result] = outcomes.get(result, 0) + n
            return {
                "started": self.started, "now": utcnow(), "pid": self.pid, "max_connections": max_connections,
                "requests": sum(self.requests.values()), "status": dict(status), "outcomes": outcomes,
                "reasons": [{"outcome": o, "reason": r, "count": n} for (o, r), n in self.outcomes.most_common()],
                "masked": dict(self.masked), "unmasked": dict(self.unmasked),
                "injection": {"observe": self.injection["observe"], "block": self.injection["block"]},
                "restored": self.restored, "residual": self.residual, "suspect": self.suspect, "new": self.new,
                "gateway_ms_avg": round((self.total_ms - self.upstream_ms) / self.total_n, 2) if self.total_n else None,
                "upstream_ms_avg": round(self.upstream_ms / self.upstream_n, 2) if self.upstream_n else None,
                "vault_sessions": dict(vault_sessions), "upstreams": dict(upstream_in_use),
                "recent": list(self.recent),
            }

    def render(self, vault_sessions: dict[str, int] | None = None, upstream_in_use: dict[str, int] | None = None) -> str:
        with self._lock:
            lines = ["# TYPE gateway_requests_total counter"]
            for (api, status, blocked), n in sorted(self.requests.items(), key=str):
                lines.append(f'gateway_requests_total{{api="{api}",status="{status}",blocked="{str(blocked).lower()}"}} {n}')
            lines.append("# TYPE gateway_outcomes_total counter")
            lines += [f'gateway_outcomes_total{{outcome="{o}",reason="{_label(r)}"}} {n}' for (o, r), n in sorted(self.outcomes.items())]
            lines.append("# TYPE gateway_injection_hits_total counter")
            lines += [f'gateway_injection_hits_total{{mode="{m}"}} {n}' for m, n in sorted(self.injection.items())]
            lines.append("# TYPE gateway_pii_masked_total counter")
            lines += [f'gateway_pii_masked_total{{kind="{_label(k)}"}} {n}' for k, n in sorted(self.masked.items())]
            lines.append("# TYPE gateway_pii_unmasked_total counter")
            lines += [f'gateway_pii_unmasked_total{{kind="{_label(k)}"}} {n}' for k, n in sorted(self.unmasked.items())]
            lines += ["# TYPE gateway_pii_restored_total counter", f"gateway_pii_restored_total {self.restored}",
                      "# TYPE gateway_pii_residual_total counter", f"gateway_pii_residual_total {self.residual}",
                      "# TYPE gateway_pii_suspect_total counter", f"gateway_pii_suspect_total {self.suspect}",
                      "# TYPE gateway_pii_new_total counter", f"gateway_pii_new_total {self.new}",
                      "# TYPE gateway_upstream_ms summary", f"gateway_upstream_ms_sum {self.upstream_ms:.2f}",
                      f"gateway_upstream_ms_count {self.upstream_n}",
                      "# TYPE gateway_total_ms summary", f"gateway_total_ms_sum {self.total_ms:.2f}",
                      f"gateway_total_ms_count {self.total_n}"]
            lines.append("# TYPE gateway_vault_sessions gauge")
            lines += [f'gateway_vault_sessions{{policy="{_label(p)}"}} {n}' for p, n in sorted((vault_sessions or {}).items())]
            lines.append("# TYPE gateway_upstream_connections_in_use gauge")
            lines += [f'gateway_upstream_connections_in_use{{upstream="{_label(u)}"}} {n}' for u, n in sorted((upstream_in_use or {}).items())]
            return "\n".join(lines) + "\n"


def _label(value: str) -> str:
    """Prometheus 레이블 값 — 역슬래시·따옴표·줄바꿈을 이스케이프한다(정책 이름·상류 주소는 운영자가 정한다)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
