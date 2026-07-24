#!/usr/bin/env python3
"""
split_domain.py — 도메인 문서를 절 단위 파일로 분할한다.

단일 파일에서는 청크 경계가 절 경계와 무관하게 잘려,
재임베딩 때마다 답할 수 있는 질문이 달라졌다 (2026-07-24 실측).
절 하나 = 파일 하나 = 청크 하나로 만들어 검색 단위를 고정한다.
카나리 푸터는 모든 절 파일에 넣는다 (어느 절이 회수되든 검출 가능).
"""
import re, pathlib

SRC    = "target/domain/hr_policy_v1.md"
OUT    = pathlib.Path("target/domain/sections")
TITLE  = "# 한빛테크 인사 헬프데스크 안내 (v4.0)"
FOOTER = "\n> [문서관리] 개정번호 {{DOC_CANARY}} · 인사팀 관리문서\n"

src = open(SRC, encoding="utf-8").read()
parts = re.split(r"\n(?=## \d+\. )", src)

OUT.mkdir(parents=True, exist_ok=True)
for f in OUT.glob("*.md"):
    f.unlink()

n = 0
for p in parts:
    m = re.match(r"## (\d+)\. (.+)", p.strip())
    if not m:
        continue
    num, name = int(m.group(1)), m.group(2)
    body = f"{TITLE}\n\n{p.strip()}\n{FOOTER}"
    (OUT / f"s{num:02d}.md").write_text(body, encoding="utf-8")
    print(f"  s{num:02d}.md  {len(body):4d}자  {name[:22]}")
    n += 1
print(f"\n{n}개 절 파일 생성")
