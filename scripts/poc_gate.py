#!/usr/bin/env python3
"""v1.0 기준 판정(D-132, PLAN 22단계) — PoC 감사 로그(JSONL)에서 의심 잔여 비율과 게이트웨이 몫 실패 비율을 잰다.

  python3 scripts/poc_gate.py audit.jsonl [audit.jsonl.1 …]      # 표준 입력은 - (파일 순서는 상관없다 — 시각으로 정렬한다)

기준(데이터를 보기 전에 D-132에 적었다): **mask로 돈 구간**(가림 검사기 `pii_mask`가 처음 나온 줄부터 — 그 앞의 관측 구간은 뺀다)이 14일 이상이고 빈 날이 없을 때
  G1 가짜 값을 발급한 요청(pii_issued > 0) 가운데 pii_suspect > 0인 요청 < 0.1%
  G2 전체 요청 가운데 게이트웨이 몫 실패 < 0.1% — status ≥ 500이거나 스트림 도중 실패(status 200 + 오류)인 줄. 상류 장애(upstream_error)와 클라이언트가 끊은 것은 뺀다(따로 센다)
분모가 1,000건 미만이면 '판정 불가'다(0.1%를 말할 수 없다). 둘 다 통과이고 기간이 충분하면 종료 코드 0, 아니면 1.
감사 로그에는 원문이 없고 이 도구도 건수만 낸다.
"""
from __future__ import annotations

import io
import json
import sys
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.metrics import outcome  # noqa: E402 — 대시보드·지표와 같은 결과 분류

LIMIT = 0.001       # 0.1%
MIN_N = 1000        # 이보다 적은 분모로는 0.1%를 판정하지 않는다
MIN_DAYS = 14
CLIENT_GONE = frozenset({"ClientDisconnect", "CancelledError"})     # 클라이언트가 끊은 요청 — 게이트웨이 몫이 아니다


def _record(line: str) -> tuple[datetime, dict] | None:
    """감사 줄이면 (시각, 줄). 잘린 줄·다른 로그·시각이 ISO가 아니거나 시간대가 없는 줄은 None."""
    try:
        rec = json.loads(line)
        when = datetime.fromisoformat(rec["ts"])
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(rec.get("request_id"), str) or when.tzinfo is None or not isinstance(rec.get("status") or 0, int):
        return None
    return when.astimezone(timezone.utc), rec


def measure(lines: Iterable[str]) -> dict:
    m: dict = {"requests": 0, "issued": 0, "suspect": 0, "gateway_failed": 0, "upstream_errors": 0, "client_gone": 0,
               "skipped": 0, "duplicates": 0, "before_mask": 0, "first": None, "last": None, "days": 0.0, "empty_days": 0}
    seen: set[str] = set()
    rows = []       # ponytail: 메모리에 모아 시각으로 정렬한다(회전된 파일을 아무 순서로 줘도 되게). 수백만 줄이면 정렬된 입력을 전제로 줄 단위로 흘린다
    for line in lines:
        if not line.strip():
            continue
        parsed = _record(line)
        if parsed is None:
            m["skipped"] += 1               # 세어 보이고 건너뛴다
        elif parsed[1]["request_id"] in seen:
            m["duplicates"] += 1            # 같은 파일을 두 번 주면 분모가 부풀려진다
        else:
            seen.add(parsed[1]["request_id"])
            rows.append(parsed)
    rows.sort(key=lambda row: row[0])
    masking, dates = False, set()
    for when, rec in rows:
        if not masking:                     # mask 구간의 시작 — 그 앞(observe로 돌린 기간)은 기간에도 분모에도 넣지 않는다
            masking = any(isinstance(d, dict) and d.get("detector") == "pii_mask" for d in rec.get("detectors") or [])
            if not masking:
                m["before_mask"] += 1
                continue
        m["requests"] += 1
        m["first"], m["last"] = m["first"] or when, when
        dates.add(when.date())
        if (rec.get("pii_issued") or 0) > 0:
            m["issued"] += 1
            m["suspect"] += (rec.get("pii_suspect") or 0) > 0
        kind = outcome(rec)[0]
        upstream, gone = kind == "upstream_error", rec.get("error") in CLIENT_GONE
        m["upstream_errors"] += upstream
        m["client_gone"] += gone
        m["gateway_failed"] += not upstream and not gone and ((rec.get("status") or 0) >= 500 or kind == "failed")
    if m["requests"]:
        m["days"] = (m["last"] - m["first"]).total_seconds() / 86400
        span = (m["last"].date() - m["first"].date()).days + 1
        m["empty_days"] = span - len(dates)                     # 줄이 하나도 없는 날(UTC) — '연속'이 아니다
    return m


def verdict(count: int, total: int) -> str:
    if total < MIN_N:
        return "판정 불가"
    return "통과" if count / total < LIMIT else "미달"


def report(m: dict) -> tuple[str, bool]:
    g1, g2 = verdict(m["suspect"], m["issued"]), verdict(m["gateway_failed"], m["requests"])
    long_enough = m["days"] >= MIN_DAYS and m["empty_days"] == 0
    ok = g1 == g2 == "통과" and long_enough

    def rate(count: int, total: int) -> str:
        return f"{count:,} / {total:,}" + (f" = {count / total:.3%}" if total else "")

    def stamp(when: datetime | None) -> str:
        return when.isoformat(timespec="seconds") if when else "—"

    period = "충분" if long_enough else f"기간 부족({MIN_DAYS}일 이상, 빈 날 없이 — 빈 날 {m['empty_days']}일)"
    left_out = [f"mask 구간 앞의 {m['before_mask']:,}줄(관측 구간)" if m["before_mask"] else "", f"감사 줄이 아닌 {m['skipped']:,}줄" if m["skipped"] else "",
                f"같은 요청 ID가 되풀이된 {m['duplicates']:,}줄" if m["duplicates"] else ""]
    rows = [
        "# v1.0 기준 판정",
        "",
        f"- mask 구간: {stamp(m['first'])} ~ {stamp(m['last'])} ({m['days']:.1f}일) — {period}",
        f"- 요청: {m['requests']:,}건" + (" (뺀 것: " + ", ".join(x for x in left_out if x) + ")" if any(left_out) else ""),
        "",
        "| 기준 | 측정 | 판정 |",
        "|---|---|---|",
        f"| G1 의심 잔여 — 가짜 값을 발급한 요청 중 복원 실패 신호가 있는 요청 < 0.1% | {rate(m['suspect'], m['issued'])} | {g1} |",
        f"| G2 게이트웨이 몫 실패(5xx + 스트림 도중 실패) — 전체 요청 중 < 0.1% | {rate(m['gateway_failed'], m['requests'])} | {g2} |",
        "",
        f"- 게이트 밖: 상류 장애(공급자 5xx·연결 실패) {rate(m['upstream_errors'], m['requests'])} · 클라이언트가 끊은 요청 {m['client_gone']:,}건",
        f"- 종합: **{'통과' if ok else '미달 또는 판정 불가'}**" + ("" if ok else f" — 분모가 {MIN_N:,}건 미만이면 판정하지 않는다"),
    ]
    return "\n".join(rows) + "\n", ok


def read(names: list[str]) -> Iterator[str]:
    for name in names:
        stream = sys.stdin.buffer if name == "-" else open(name, "rb")
        with io.TextIOWrapper(stream, encoding="utf-8", errors="replace") as text:     # 깨진 바이트 한 줄로 전체가 죽지 않는다
            yield from text


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(2)
    text, ok = report(measure(read(sys.argv[1:])))
    print(text, end="")
    sys.exit(0 if ok else 1)
