"""한국어 PII NER 실행기(D-125) — tokenizers로 자르고 ONNX Runtime(CPU)으로 돌려 decode.py로 구간을 뽑는다. torch·transformers 없이 돈다.

모델은 `detect/models.json`의 이름 하나다(고정 리비전·파일 SHA-256). 파일은 `fetch.py`가 `<모델 폴더>/<이름>/`에 받는다. 열 때 파일마다 바이트를 한 번 읽어
SHA-256을 재고 그 바이트로 연다 — 목록과 다르면 기동하지 않고, /health가 알리는 해시는 실제로 돈 바이트의 해시다(재고 나서 다시 여는 틈이 없다).
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Regex, Tokenizer, normalizers, pre_tokenizers
from tokenizers.models import WordPiece

from detect.decode import log_softmax, scheme, tag_spans, tidy, viterbi, windows
from detect.fetch import MODELS


class NER:
    def __init__(self, name: str, root: Path, threads: int = 4, max_len: int = 512, stride: int = 128) -> None:
        spec = MODELS[name]
        folder = root / name
        data: dict[str, bytes] = {}
        for file, want in spec["files"].items():
            data[file] = (folder / file).read_bytes()
            got = hashlib.sha256(data[file]).hexdigest()
            if got != want:
                raise RuntimeError(f"{name}: {file}의 SHA-256이 목록과 다르다({got[:12]} != {want[:12]}) — fetch.py로 다시 받는다")
        self.name, self.spec, self.sha256 = name, spec, spec["files"][spec["onnx"]]
        self.tok = Tokenizer.from_str(data["tokenizer.json"].decode("utf-8"))
        # 풀어 쓴 한글(NFD 자모 — macOS 파일 이름·복사한 글에서 흔하다)은 모든 후보가 낱말째 [UNK]나 처음 보는 조각으로 보고, 이름 뒤 결합 부호 하나(U+0301)도
        # WordPiece 낱말 전체를 [UNK]로 만든다 — 모아 쓰고 결합 부호를 뺀 뒤 자른다. 위치는 원문으로 돌아오지만 모은 글자의 끝은 첫 자모를 가리키므로
        # 구간 끝을 뒤따르는 자모·결합 부호까지 늘린다(predict)
        steps = [normalizers.NFC(), normalizers.Replace(Regex(r"\p{Mn}"), "")]
        self.tok.normalizer = normalizers.Sequence(steps + ([self.tok.normalizer] if self.tok.normalizer else []))
        if isinstance(self.tok.model, WordPiece) and self.tok.pre_tokenizer is not None:
            # WordPiece는 띄어쓰기·구두점 없이 상한(100자)을 넘는 덩어리를 통째로 [UNK] 하나로 만든다 — 붙여 쓴 긴 줄 속 이름을 못 본다. 상한을 풀면
            # 덩어리 길이의 제곱 시간이다(2만 자 한 낱말에 273초 — 서비스 거부). 상한은 두고 덩어리를 위치를 지킨 채 상한 길이씩 자른다(70만 자 3초)
            n = self.tok.model.max_input_chars_per_word
            self.tok.pre_tokenizer = pre_tokenizers.Sequence([self.tok.pre_tokenizer, pre_tokenizers.Split(Regex(rf"\S{{1,{n}}}"), "isolated")])
        self.tok.no_truncation()
        self.tok.no_padding()
        self.cls, self.sep = (self.tok.token_to_id(t) for t in spec.get("specials", ("[CLS]", "[SEP]")))
        config = json.loads(data["config.json"])
        self.scheme = scheme({int(k): v for k, v in config["id2label"].items()})
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(data[spec["onnx"]], options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.max_len, self.stride = spec.get("max_len", max_len), spec.get("stride", stride)     # 모델이 학습한 창(newmean은 256·64)
        self.kinds: dict[str, str] = spec.get("kinds", {})
        self.merge = frozenset(spec.get("merge", ()))
        # 디코딩은 모델을 만든 쪽이 적은 방식을 따른다 — veil은 제약 비터비(veil.py), 카드가 argmax를 보여 주는 BIO 모델은 argmax(규칙 밖 I-는 tag_spans가 새 구간으로 연다)
        self.viterbi = spec.get("decode", "viterbi") == "viterbi"

    def info(self) -> dict:
        return {"model": self.spec["id"], "revision": self.spec["revision"], "license": self.spec["license"], "sha256": self.sha256}

    def encode(self, text: str):
        return self.tok.encode(text, add_special_tokens=False)

    def tokens(self, text: str) -> int:
        return len(self.encode(text).ids)

    def _logprobs(self, ids: list[int]) -> np.ndarray:
        x = np.array([[self.cls, *ids, self.sep]], dtype=np.int64)
        feeds = {"input_ids": x, "attention_mask": np.ones_like(x), "token_type_ids": np.zeros_like(x)}
        logits = self.session.run(None, {k: v for k, v in feeds.items() if k in self.inputs})[0][0]
        return log_softmax(logits[1:-1])

    def predict(self, text: str, enc=None) -> list[dict]:
        """원문 문자 위치의 구간 목록 [{start, end, label, kind, score}] — kind는 제품 종류(person·address·org), 없으면 None. enc는 이미 자른 결과(encode)."""
        enc = enc or self.encode(text)
        ids, offsets = enc.ids, enc.offsets
        if not ids:
            return []
        tags: list[str] = []
        probs: list[float] = []
        for a, b, own_a, own_b in windows(len(ids), self.max_len - 2, self.stride):
            lp = self._logprobs(ids[a:b])
            path = viterbi(lp, self.scheme) if self.viterbi else lp.argmax(1).tolist()
            for i in range(own_a - a, own_b - a):
                tags.append(self.scheme.labels[path[i]])
                probs.append(float(np.exp(lp[i, path[i]])))
        raw = tag_spans(tags, probs, offsets)
        for sp in raw:                                   # 잇기·조사 떼기 전에 — 모은 글자의 끝이 첫 자모를 가리키면 붙은 주소 조각 사이가 한 칸보다 넓어 보인다
            while sp["end"] < len(text) and _attached(text[sp["end"]]):
                sp["end"] += 1
        spans = tidy(raw, text, self.kinds, self.merge)
        return [{**sp, "kind": self.kinds.get(sp["label"])} for sp in spans]


def _attached(c: str) -> bool:
    """앞 글자에 붙는 글자 — 한글 중성·종성 자모(조합형)와 결합 부호."""
    return "\u1160" <= c <= "\u11ff" or "\ud7b0" <= c <= "\ud7ff" or unicodedata.category(c) in ("Mn", "Me")
