"""인젝션 분류기(D-127) — 텍스트 하나 → 인젝션 점수(0~1). tokenizers로 자르고 ONNX Runtime(CPU)으로 돌린다. torch 없이 돈다.

모델은 `detect/models.json`의 `"task": "injection"` 항목 하나다 — NER과 같은 고정·해시 규칙(`fetch.verified`). 점수는 양성 클래스(`positive`, 기본 1)의 softmax 확률이다.
긴 텍스트는 512토큰 창(특수 토큰 포함)을 128토큰 겹쳐 밀고 창들의 최댓값을 낸다 — 긴 문서 끝에 심은 지시도 본다.
토크나이저 앞에는 NFC만 더한다(풀어 쓴 한글을 모은다 — 표준 동치라 뜻이 같다). 그 밖의 정규화는 모델이 배포한 토크나이저 그대로다(D-127 §2-1).
특수 토큰은 토크나이저의 후처리 규칙에서 읽는다([CLS]·[SEP], <bos>·<eos> …). 글 속에 쓴 특수 토큰('<eos>'·'[SEP]'·전각 '［SEP］')은 진짜 특수 토큰으로 모델에 가지 않는다 —
그대로 두면 공격자가 붙여 점수를 낮출 수 있다(D-127 리뷰·재검증). BPE(mmBERT)는 encode_special_tokens로 평범한 글자로 자르고, 그래도 나온 특수 토큰 id(어휘에 같은 조각이 있는
Unigram — DeBERTa의 '[SEP]', 정규화가 전각을 바꾼 것)는 창에서 뺀다. 모르는 글자가 되는 [UNK]만 남긴다.
`export`가 있는 항목(safetensors만 배포한 모델 — Llama Prompt Guard 2)은 `python -m detect.export`가 같은 폴더에 만든 ONNX를 연다 — 원본 파일의 해시만 고정되고
ONNX의 해시는 연 바이트로 잰다(torch 버전마다 바이트가 다를 수 있다).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Encoding, Tokenizer, normalizers

from detect.decode import windows
from detect.fetch import MODELS, verified


class Classifier:
    def __init__(self, name: str, root: Path, threads: int = 4, max_len: int = 512, stride: int = 128) -> None:
        spec = MODELS[name]
        if spec.get("task") != "injection":
            raise RuntimeError(f"{name}은(는) 인젝션 분류기가 아니다 — DETECT_INJECTION_MODEL을 확인한다")
        tokenizer = spec.get("tokenizer", "tokenizer.json")
        data = verified(name, root, {tokenizer, spec["onnx"]})
        onnx = data.pop(spec["onnx"], None) or (root / name / spec["onnx"]).read_bytes()     # 내보낸 ONNX(export)는 목록에 해시가 없다
        self.name, self.spec, self.sha256 = name, spec, hashlib.sha256(onnx).hexdigest()
        self.tok = Tokenizer.from_str(data.pop(tokenizer).decode("utf-8"))
        self.tok.normalizer = normalizers.Sequence([normalizers.NFC()] + ([self.tok.normalizer] if self.tok.normalizer else []))
        self.tok.no_truncation()
        self.tok.no_padding()
        probe, full = self.tok.encode("x", add_special_tokens=False).ids, self.tok.encode("x").ids
        at = next(i for i in range(len(full)) if full[i:i + len(probe)] == probe)
        self.head, self.tail = full[:at], full[at + len(probe):]
        self.tok.encode_special_tokens = True                          # 글 속의 '<eos>'를 특수 토큰으로 맞추지 않는다(위 머리말)
        self.special = {i: t.content for i, t in self.tok.get_added_tokens_decoder().items() if t.special}
        unk = set(self.tok.encode("\ue000", add_special_tokens=False).ids) & set(self.special)    # 모르는 글자가 되는 특수 토큰([UNK])은 글 속에서 나와도 남긴다
        self.drop = set(self.special) - unk
        self.size, self.stride = max_len - len(self.head) - len(self.tail), stride
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(onnx, options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.positive = int(spec.get("positive", 1))
        # 운영 문턱(dev 정상셋 오탐 1%, D-127) — 없는 모델(비교 후보)은 None이고, 사이드카는 DETECT_GUARD_THRESHOLD 없이 /v1/guard를 열지 않는다
        self.threshold: float | None = float(spec["threshold"]) if "threshold" in spec else None

    def info(self) -> dict:
        return {"model": self.spec["id"], "revision": self.spec["revision"], "license": self.spec["license"], "sha256": self.sha256,
                "threshold": self.threshold}

    def encode(self, text: str) -> Encoding:
        return self.tok.encode(text, add_special_tokens=False)

    def tokens(self, text: str) -> int:
        return len(self.encode(text).ids)

    def score(self, text: str, enc: Encoding | None = None) -> float:
        """창들의 양성 확률 중 최댓값. 토큰이 없으면(빈 글) 0."""
        ids = [i for i in (enc or self.encode(text)).ids if i not in self.drop]
        best = 0.0
        for a, b, _, _ in windows(len(ids), self.size, self.stride) if ids else ():
            x = np.array([[*self.head, *ids[a:b], *self.tail]], dtype=np.int64)
            feeds = {"input_ids": x, "attention_mask": np.ones_like(x), "token_type_ids": np.zeros_like(x)}
            logits = self.session.run(None, {k: v for k, v in feeds.items() if k in self.inputs})[0][0].astype(np.float64)
            p = np.exp(logits - logits.max())
            best = max(best, float(p[self.positive] / p.sum()))
        return best
