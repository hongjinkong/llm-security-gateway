"""운영 지표 — `/__gateway/metrics`, Prometheus 텍스트 형식, 의존성 없음(D-107 E).

감사 레코드 하나에서 전부 센다(`AuditLog.on_write`). 프로세스 메모리의 카운터라 워커·재시작 단위다.
  gateway_requests_total{api,status,blocked}   요청 수
  gateway_injection_hits_total{mode}           인젝션 룰 적중(observe는 would_block, block은 차단·가림)
  gateway_pii_masked_total{kind}               마스킹 건수(종류별)
  gateway_pii_restored_total / gateway_pii_residual_total   복원 건수 / 복원 뒤 남은 대체값 수
  gateway_upstream_ms_sum/_count, gateway_total_ms_sum/_count   지연 합·횟수(평균은 나눠서)
"""
from __future__ import annotations

import threading
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Counter = Counter()
        self.injection: Counter = Counter()
        self.masked: Counter = Counter()
        self.restored = self.residual = 0
        self.upstream_ms = self.total_ms = 0.0
        self.upstream_n = self.total_n = 0

    def observe(self, rec: dict) -> None:
        with self._lock:
            self.requests[(rec.get("api") or "other", rec.get("status"), bool(rec.get("blocked")))] += 1
            for d in rec.get("detectors") or []:
                name = d.get("detector", "")
                if name.startswith("injection") and (d.get("rules") or d.get("would_block")):
                    self.injection["observe" if name == "injection_observe" else "block"] += 1
                if name in ("pii", "pii_mask"):
                    for kind, n in (d.get("pii") or {}).items():
                        self.masked[kind] += n
            for d in rec.get("response_detectors") or []:
                if d.get("detector") == "pii_mask":
                    self.restored += d.get("restored") or 0
                    self.residual += d.get("residual_tokens") or 0
            if rec.get("total_ms") is not None:
                self.total_ms += rec["total_ms"]
                self.total_n += 1
            if rec.get("upstream_ms") is not None:
                self.upstream_ms += rec["upstream_ms"]
                self.upstream_n += 1

    def render(self) -> str:
        with self._lock:
            lines = ["# TYPE gateway_requests_total counter"]
            for (api, status, blocked), n in sorted(self.requests.items(), key=str):
                lines.append(f'gateway_requests_total{{api="{api}",status="{status}",blocked="{str(blocked).lower()}"}} {n}')
            lines.append("# TYPE gateway_injection_hits_total counter")
            lines += [f'gateway_injection_hits_total{{mode="{m}"}} {n}' for m, n in sorted(self.injection.items())]
            lines.append("# TYPE gateway_pii_masked_total counter")
            lines += [f'gateway_pii_masked_total{{kind="{k}"}} {n}' for k, n in sorted(self.masked.items())]
            lines += ["# TYPE gateway_pii_restored_total counter", f"gateway_pii_restored_total {self.restored}",
                      "# TYPE gateway_pii_residual_total counter", f"gateway_pii_residual_total {self.residual}",
                      "# TYPE gateway_upstream_ms summary", f"gateway_upstream_ms_sum {self.upstream_ms:.2f}",
                      f"gateway_upstream_ms_count {self.upstream_n}",
                      "# TYPE gateway_total_ms summary", f"gateway_total_ms_sum {self.total_ms:.2f}",
                      f"gateway_total_ms_count {self.total_n}"]
            return "\n".join(lines) + "\n"
