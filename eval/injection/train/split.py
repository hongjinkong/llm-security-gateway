"""D-128 분할 규칙 — 표준 라이브러리만(httpx 없이). 학습 데이터 빌더(build.py)와 평가(detect/evaluate_injection.py)가 같은 함수를 쓴다.

dev의 그룹마다 SHA-256("d128\\x1f" + group) 첫 바이트 < 128이면 학습 쪽(dev-train), 아니면 평가 쪽(dev-eval). 소금 d128 — 평가셋의 분할 해시(_sha(group))·뽑기 해시(pick\\x1f)와 상관이 없다.
학습 그룹 가운데 SHA-256("val\\x1f" + group) 첫 바이트 < 26(약 10%)은 학습용 검증 분할(val.jsonl, epoch 고르기에만).
"""
from __future__ import annotations

import hashlib


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def dev_side(group: str) -> str:
    """dev 그룹의 쪽: 'train'(학습) 또는 'eval'(문턱·모델 고르기)."""
    return "train" if int(_sha("d128\x1f" + group)[:2], 16) < 128 else "eval"


def is_val(group: str) -> bool:
    """학습 그룹 가운데 약 10%는 학습용 검증 분할."""
    return int(_sha("val\x1f" + group)[:2], 16) < 26


def frac(key: str, num: int, den: int) -> bool:
    """결정적 표본 선택 — key의 해시가 den 칸 중 앞 num 칸에 들면 참."""
    return int(_sha(key)[:4], 16) % den < num
