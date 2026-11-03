"""모델 파일 받기(D-125) — `detect/models.json`의 고정 리비전에서 받아 SHA-256을 맞춘다. 표준 라이브러리만(onnxruntime 없이 돈다).

  python -m detect.fetch veil-ko-lite-int8 --dir models      # models/veil-ko-lite-int8/에 받는다. 이미 맞는 파일은 건너뛴다

Hugging Face 주소는 리비전(커밋 SHA)으로 고정하므로 저장소가 바뀌어도 같은 파일이다. 해시가 다르면 받은 파일을 지우고 실패한다.
승인이 필요한 저장소(`"gated": true` — Llama Prompt Guard 2, D-127)는 토큰을 `HF_TOKEN` 또는 `~/.cache/huggingface/token`(`hf auth login`이 쓰는 곳)에서 읽어 헤더로만 보낸다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
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


def verified(name: str, root: Path, keep: set[str] | None = None) -> dict[str, bytes]:
    """목록의 파일마다 SHA-256을 맞춘다 — 다르면 기동하지 않는다. keep(없으면 전부)의 바이트는 한 번 읽어 재고 그 바이트를 돌려준다 — 그 바이트로 열므로 재고 나서
    다시 여는 틈이 없다(D-125). 쓰지 않는 파일(내보내기 원본 safetensors 등)은 흘려 읽어 해시만 잰다 — 메모리에 올리지 않는다(D-127 리뷰)."""
    data: dict[str, bytes] = {}
    for file, want in MODELS[name]["files"].items():
        if keep is None or file in keep:
            data[file] = (root / name / file).read_bytes()
            got = hashlib.sha256(data[file]).hexdigest()
        else:
            got = sha256(root / name / file)
        if got != want:
            raise RuntimeError(f"{name}: {file}의 SHA-256이 목록과 다르다({got[:12]} != {want[:12]}) — fetch.py로 다시 받는다")
    return data


class _SameHostAuth(urllib.request.HTTPRedirectHandler):
    """리다이렉트에 토큰을 같은 호스트(huggingface.co → huggingface.co)로만 옮긴다 — 승인 저장소의 작은 파일은 같은 호스트의 다른 주소로 돌려보내고(토큰이 없으면 401),
    큰 파일은 CDN으로 보낸다(토큰을 보내지 않는다, D-127 재검증)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        auth = req.unredirected_hdrs.get("Authorization")
        if new is not None and auth and urllib.parse.urlsplit(newurl).hostname == urllib.parse.urlsplit(req.full_url).hostname:
            new.add_unredirected_header("Authorization", auth)
        return new


def _token() -> str:
    path = Path.home() / ".cache" / "huggingface" / "token"
    return os.environ.get("HF_TOKEN", "").strip() or (path.read_text().strip() if path.exists() else "")


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
        token = _token() if spec.get("gated") else ""
        request = urllib.request.Request(url)
        if token:                       # 다른 호스트(CDN)로의 리다이렉트에는 옮기지 않는다 — 토큰은 huggingface.co에만 간다(D-127 리뷰·재검증)
            request.add_unredirected_header("Authorization", f"Bearer {token}")
        with urllib.request.build_opener(_SameHostAuth).open(request, timeout=60) as response, part.open("wb") as out:
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
    ap.add_argument("names", nargs="+", help="models.json의 이름 — 받을 것만 적는다(승인 저장소까지 다 받지 않게)")
    ap.add_argument("--dir", type=Path, default=Path("models"))
    a = ap.parse_args()
    for name in a.names:
        fetch(name, a.dir)


if __name__ == "__main__":
    main()
