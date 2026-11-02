"""토큰 분류 출력 → 문자 구간(D-125). numpy만 쓴다 — 모델·토크나이저를 모르는 순수 함수라 가짜 로짓으로 시험한다.

1. 제약 비터비: BIO·BIOES 규칙을 어기는 태그 열(`O` 다음 `I-X`, `B-PERSON` 다음 `E-ADDRESS`)을 고르지 않는다. 그냥 argmax하면 깨진 구간이 섞인다.
   규칙이 '허용/불가' 둘뿐이라 앞 태그의 최댓값을 두 무리(끝날 수 있는 태그 전체, 같은 종류의 B·I)에서만 찾는다 — 걸음마다 O(라벨 수).
2. 긴 입력의 창: 창(최대 max_len 토큰)을 stride만큼 겹쳐 밀고, 겹친 구간은 가운데를 경계로 앞뒤 창이 나눠 갖는다. 태그를 전체 토큰 열에 이어 붙인 뒤 구간을 한 번 뽑는다.
3. 뒷손질: 앞뒤 공백을 떼고, 이름 끝의 조사·호칭('에게' '님' '씨')과 숫자로 끝나는 구간 뒤의 조사를 뗀다. 공백 하나 이내로 붙은 주소 조각은 잇는다.
   조사 떼기 규칙과 주소 잇기는 1T/veil-pii-ko-lite의 veil.py(Apache-2.0, Wontae Kim)의 규칙을 옮겨 왔다 — 모델을 만든 쪽의 디코더 그대로 재야 공정하다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

NEG = -1e4


@dataclass(frozen=True)
class Scheme:
    """라벨 목록에서 만든 비터비 규칙."""

    labels: tuple[str, ...]
    starters: np.ndarray        # 끝난 태그 다음에 올 수 있는 태그: O·B-·S- (BIO에서는 O·B-)
    enders: np.ndarray          # 다음에 starters가 올 수 있는 태그: O·E-·S- (BIO에서는 전부)
    cont: np.ndarray            # 같은 종류의 앞 태그가 필요한 태그: I-·E- (BIO에서는 I-)
    cont_prev: np.ndarray       # cont마다 (같은 종류의 B-, 같은 종류의 I-) 위치, 없으면 -1


def scheme(id2label: dict[int, str]) -> Scheme:
    labels = tuple(id2label[i] for i in range(len(id2label)))
    split = [("O", "") if x == "O" else tuple(x.split("-", 1)) for x in labels]
    bioes = any(p in ("E", "S", "L", "U") for p, _ in split)
    pos = {(p, t): i for i, (p, t) in enumerate(split)}
    starters = [i for i, (p, _) in enumerate(split) if p in ("O", "B", "S", "U")]
    enders = [i for i, (p, _) in enumerate(split) if not bioes or p in ("O", "E", "S", "L", "U")]
    cont = [i for i, (p, _) in enumerate(split) if p in ("I", "E", "L")]
    prev = [[pos.get(("B", split[i][1]), -1), pos.get(("I", split[i][1]), -1)] for i in cont]
    return Scheme(labels, np.array(starters), np.array(enders), np.array(cont, dtype=np.int64),
                  np.array(prev, dtype=np.int64).reshape(-1, 2))


def log_softmax(logits: np.ndarray) -> np.ndarray:
    x = logits.astype(np.float32)
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


def viterbi(lp: np.ndarray, sc: Scheme) -> list[int]:
    """lp: (토큰 수, 라벨 수) 로그 확률 → 규칙을 지키는 가장 그럴듯한 태그 열."""
    n_tok, n_lab = lp.shape
    score = np.full(n_lab, NEG, np.float32)
    score[sc.starters] = lp[0, sc.starters]
    back = np.zeros((n_tok, n_lab), np.int64)
    has_prev = sc.cont_prev >= 0
    rows = np.arange(len(sc.cont))
    for t in range(1, n_tok):
        e = sc.enders[int(score[sc.enders].argmax())]
        new = np.full(n_lab, NEG, np.float32)
        new[sc.starters] = score[e] + lp[t, sc.starters]
        back[t, sc.starters] = e
        if len(sc.cont):
            cand = np.where(has_prev, score[np.maximum(sc.cont_prev, 0)], NEG)      # (cont, 2)
            pick = cand.argmax(1)
            new[sc.cont] = cand[rows, pick] + lp[t, sc.cont]
            back[t, sc.cont] = sc.cont_prev[rows, pick]
        score = new
    final = np.full(n_lab, NEG, np.float32)
    final[sc.enders] = score[sc.enders]
    path = [int(final.argmax())]
    for t in range(n_tok - 1, 0, -1):
        path.append(int(back[t, path[-1]]))
    return path[::-1]


def windows(n: int, size: int, stride: int) -> list[tuple[int, int, int, int]]:
    """n개 토큰을 size씩 stride 겹쳐 자른 창 (시작, 끝, 가질 시작, 가질 끝). 가질 구간을 이어 붙이면 [0, n)을 빈틈없이 한 번씩 덮는다(0 <= stride < size)."""
    if not 0 <= stride < size:
        raise ValueError(f"창 겹침은 0 이상 창 크기 미만이어야 한다: size={size} stride={stride}")
    if n <= size:
        return [(0, n, 0, n)]
    starts = list(range(0, n - size, size - stride)) + [n - size]
    spans = [(a, a + size) for a in starts]
    cuts = [0] + [(spans[k + 1][0] + spans[k][1]) // 2 for k in range(len(spans) - 1)] + [n]
    return [(a, b, cuts[k], cuts[k + 1]) for k, (a, b) in enumerate(spans)]


def tag_spans(tags: list[str], probs: list[float], offsets: list[tuple[int, int]]) -> list[dict]:
    """태그 열 → 구간. B·S가 아니어도 종류가 바뀌거나 O 뒤면 새 구간으로 시작한다(창 경계에서 규칙이 이어지지 않아도 구간을 잃지 않게).
    열린 구간 안에서 시작하는 같은 라벨 토큰은 B-여도 그 구간을 늘린다 — SentencePiece의 홀로 선 '▁'과 첫 글자, 바이트 조각은 같은 위치를 나눠 갖는다."""
    out: list[dict] = []
    cur: dict | None = None
    for tag, p, (s, e) in zip(tags, probs, offsets):
        if e <= s:
            continue
        if tag == "O":
            cur = None
            continue
        pre, lab = tag.split("-", 1)
        last = cur if cur is not None else (out[-1] if out else None)      # 방금 S-로 닫힌 구간과 같은 위치를 나눠 가진 토큰도
        if last is not None and last["label"] == lab and s < last["end"]:
            last["end"] = max(last["end"], e)
            last["p"].append(p)
            cur = last
        elif pre in ("B", "S", "U") or cur is None or cur["label"] != lab:
            cur = {"start": s, "end": e, "label": lab, "p": [p]}
            out.append(cur)
        else:
            cur["end"] = e
            cur["p"].append(p)
        if pre in ("E", "S", "L", "U"):
            cur = None
    for sp in out:
        sp["score"] = round(float(np.mean(sp.pop("p"))), 4)
    return out


# --- 조사 떼기(veil.py에서 옮김) -----------------------------------------------------------
PARTICLE_NUM = re.compile(r"(이라고|이라는|으로부터|에서는|에서도|까지는|까지도|부터는|부터|까지|으로|이나|이랑|이며|이고|이다|에서|에게|한테|처럼|보다|이면|이야|"
                          r"이가|이는|은|는|이|가|을|를|로|에|의|도|과|와|랑|만)$")
PARTICLE_PER = re.compile(r"(이라고|이랑|한테|에게|이는|이가|은|는|을|를|도|의|과|와|랑|야|아|님|씨)$")
NUM_END = re.compile(r"[0-9일년월호번층동실]$")
WEAK = frozenset(("이", "가", "은", "는", "을", "를", "도", "의", "과", "와", "랑"))


def _vocative_ok(v: str, p: str) -> bool:
    """호격 '아/야'는 앞 음절 받침에 따라 갈린다: 지훈아(받침 있음)·철수야(없음). 수아·서아의 '아'는 이름의 일부다."""
    if p not in ("아", "야") or len(v) < 2:
        return True
    c = ord(v[-2])
    has_final = 0xAC00 <= c <= 0xD7A3 and (c - 0xAC00) % 28 != 0
    return has_final if p == "아" else not has_final


def tidy(spans: list[dict], text: str, kinds: dict[str, str] | None = None, merge: frozenset[str] = frozenset({"address"})) -> list[dict]:
    """공백 떼기 → 조사 떼기 → 공백 하나 이내로 붙은 같은 제품 종류(기본 주소) 잇기. spans는 위치 순이다.
    kinds는 모델 라벨 → 제품 종류(없으면 라벨 그대로) — 시·도를 LOCATION, 도로명을 STREET_ADDRESS로 나눠 다는 모델도 주소 하나로 잇는다."""
    kinds = kinds or {}
    res: list[dict] = []
    for sp in spans:
        s, e = sp["start"], sp["end"]
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        v = text[s:e]
        kind = kinds.get(sp["label"], sp["label"])
        if kind == "person":
            m = PARTICLE_PER.search(v)
            if m and not _vocative_ok(v, m.group(1)):
                m = None
            if m and ((len(v) - len(m.group(1)) >= 2 and m.group(1) not in WEAK) or len(v) - len(m.group(1)) >= 3):
                e -= len(m.group(1))
        else:
            m = PARTICLE_NUM.search(v)
            if m and NUM_END.search(v[:len(v) - len(m.group(1))] or "") and len(v) - len(m.group(1)) >= 2:
                e -= len(m.group(1))
        while e > s and text[e - 1].isspace():           # '김철수 님'에서 '님'을 뗀 뒤의 공백
            e -= 1
        if e <= s:
            continue
        if res and kind in merge and kinds.get(res[-1]["label"], res[-1]["label"]) == kind and s - res[-1]["end"] <= 1 \
                and not text[res[-1]["end"]:s].strip():
            res[-1] = {**res[-1], "end": e, "score": min(res[-1]["score"], sp["score"])}
        else:
            res.append({"start": s, "end": e, "label": sp["label"], "score": sp["score"]})
    return res
