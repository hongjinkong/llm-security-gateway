"""모델 파일 받기(D-125) — `detect/models.json`의 고정 리비전에서 받아 SHA-256을 맞춘다. 표준 라이브러리만(onnxruntime 없이 돈다).

  python -m detect.fetch veil-ko-lite-int8 --dir models      # models/veil-ko-lite-int8/에 받는다. 이미 맞는 파일은 건너뛴다

Hugging Face 주소는 리비전(커밋 SHA)으로 고정하므로 저장소가 바뀌어도 같은 파일이다. 해시가 다르면 받은 파일을 지우고 실패한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co"
MODELS = json.loads((Path(__file__).with_name("models.json")).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(name: str, root: Path) -> Path:
    spec = MODELS[name]
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    for file, want in spec["files"].items():
        path = folder / file
        path.parent.mkdir(parents=True, exist_ok=True)          # onnx/model.onnx처럼 하위 폴더에 든 파일
        if path.exists() and sha256(path) == want:
            continue
        url = f"{BASE}/{spec['id']}/resolve/{spec['revision']}/{file}"
        part = path.with_name(path.name + ".part")
        with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as out:
            while block := response.read(1 << 20):
                out.write(block)
        got = sha256(part)
        if got != want:
            part.unlink()
            raise SystemExit(f"{name}: {file} SHA-256 불일치 {got} != {want}")
        part.replace(path)
        print(f"{name}: {file} 받음", file=sys.stderr)
    return folder


def main() -> None:
    ap = argparse.ArgumentParser(description="모델 파일 받기(D-125)")
    ap.add_argument("names", nargs="*", default=sorted(MODELS))
    ap.add_argument("--dir", type=Path, default=Path("models"))
    a = ap.parse_args()
    for name in a.names:
        fetch(name, a.dir)


if __name__ == "__main__":
    main()
