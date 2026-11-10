"""릴리스 노트(D-130): 태그 버전이 pyproject.toml·CHANGELOG와 같은지 확인하고, CHANGELOG의 그 버전 절(+ 이미지 다이제스트·검증 명령)을 stdout에 낸다.

release.yml이 두 번 부른다 — 빌드 전에 확인만(`release_notes.py 0.2.0`), 서명 뒤에 노트(`--repo owner/name --image ghcr.io/…@sha256:…` 이미지마다).
어긋나면 메시지와 함께 종료 코드 1(아무것도 빌드·푸시하기 전이다). 표준 라이브러리만 쓴다 — 러너의 python3로 돈다.
"""
from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://token.actions.githubusercontent.com"   # GitHub Actions OIDC — cosign keyless 서명의 발급자


def notes(version: str, repo: str = "", images: list[str] | None = None) -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if project != version:
        raise SystemExit(f"태그 버전 {version} != pyproject.toml 버전 {project}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(rf"^## {re.escape(version)} — [^\n]*\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if not section or not section[1].strip():
        raise SystemExit(f"CHANGELOG.md에 '## {version} — ' 절이 없다(또는 비었다)")
    out = [section[1].strip()]
    if images:
        # 서명한 신원 = 이 저장소의 release.yml이 이 태그에서 돈 것. 다른 워크플로·다른 태그의 서명은 검증에서 떨어진다
        identity = f"https://github.com/{repo}/.github/workflows/release.yml@refs/tags/v{version}"
        flags = f"--certificate-identity {identity} --certificate-oidc-issuer {ISSUER}"
        out += ["", "## 이미지", "", *(f"- `{ref}`" for ref in images), "",
                "서명과 SBOM 증명 검증(cosign 3 이상, 이미지마다):", "", "```"]
        for ref in images:
            out += [f"cosign verify {flags} {ref}", f"cosign verify-attestation --type spdxjson {flags} {ref}"]
        out += ["```", "", "SBOM(SPDX JSON)은 이 릴리스의 첨부 파일과 이미지의 증명(attestation)에 있다.",
                "탐지 사이드카 이미지에 든 모델과 그 라이선스는 이미지의 `/licenses/THIRD_PARTY_NOTICES.md`(저장소 `detect/THIRD_PARTY_NOTICES.md`)에 있다."]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", help="v를 뗀 태그 — 예: 0.2.0")
    ap.add_argument("--repo", default="", help="owner/name — 검증 명령의 서명 신원")
    ap.add_argument("--image", action="append", help="이미지@다이제스트(여러 번)")
    args = ap.parse_args()
    print(notes(args.version, args.repo, args.image), end="")
