#!/usr/bin/env python3
"""
setup_target.py — 타겟 앱을 확정된 측정 조건으로 구성한다.
이 파일이 타겟 상태의 단일 출처다. 브라우저에서 손으로 바꾸지 않는다.
"""
import json, os, sys, time, urllib.request, uuid, pathlib

# 저장소 루트를 경로에 넣고 지문 함수를 빌려온다. 세 곳(.env / health / 여기)이
# **같은 계산식**을 써야 대조가 성립한다(D-058 R5). gateway.version은 hashlib과
# pathlib만 쓰므로 여기서 import해도 게이트웨이 의존성이 딸려오지 않는다.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from gateway.version import canary_fingerprint  # noqa: E402

BASE = os.environ["TARGET_URL"]
SLUG = os.environ["WORKSPACE_SLUG"]
AUTH = {"Authorization": f"Bearer {os.environ['TARGET_API_KEY']}"}
JSON = {**AUTH, "Content-Type": "application/json"}

DOC_DIR = pathlib.Path("target/domain/sections")   # D-012: 절 단위 분할
SYS     = "target/system_prompt.md"
SETTINGS = {
    "topN": 2,
    "openAiHistory": 0,      # D-015: 시도 간 독립성 확보. 이력 누적 시 컨텍스트 초과로 500 발생

    "similarityThreshold": 0.25,
    "openAiTemp": 0.7,
    "chatMode": "query",
}

def call(path, data=None, method=None, headers=JSON):
    req = urllib.request.Request(f"{BASE}/api/v1/{path}",
            data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)

sys_prompt = open(SYS).read().split("-->", 1)[1].strip()
sys_prompt = (sys_prompt.replace("{{CANARY_A}}", os.environ["CANARY_A_TOKEN"])
                        .replace("{{CANARY_B}}", os.environ["CANARY_B_TOKEN"]))
call(f"workspace/{SLUG}/update",
     json.dumps({**SETTINGS, "openAiPrompt": sys_prompt}).encode())

docs = call("documents", headers=AUTH)
names = [f"custom-documents/{f['name']}"
         for fo in docs["localFiles"]["items"] for f in fo.get("items", [])]
if names:
    call("system/remove-documents", json.dumps({"names": names}).encode(), "DELETE")
print(f"기존 문서 제거: {len(names)}")

tok = os.environ["DOC_CANARY_TOKEN"]
files = sorted(DOC_DIR.glob("*.md"))
if not files:
    sys.exit(f"오류: {DOC_DIR} 에 파일이 없습니다")

for fp in files:
    body = fp.read_text(encoding="utf-8").replace("{{DOC_CANARY}}", tok)
    b = uuid.uuid4().hex
    parts = (f'--{b}\r\nContent-Disposition: form-data; name="file"; '
             f'filename="{fp.name}"\r\nContent-Type: text/markdown\r\n\r\n'
             ).encode() + body.encode() + \
            (f'\r\n--{b}\r\nContent-Disposition: form-data; name="addToWorkspaces"'
             f'\r\n\r\n{SLUG}\r\n--{b}--\r\n').encode()
    call("document/upload", parts,
         headers={**AUTH, "Content-Type": f"multipart/form-data; boundary={b}"})
    print(f"  업로드 {fp.name}")
    time.sleep(2)

print(f"문서 업로드: {len(files)}개")
time.sleep(20)

w = call(f"workspace/{SLUG}", headers=AUTH)["workspace"][0]
ok = True
for k, v in SETTINGS.items():
    if w.get(k) != v:
        print(f"  불일치 {k}: 기대 {v!r} / 실제 {w.get(k)!r}"); ok = False
if (w.get("openAiPrompt") or "").strip() != sys_prompt.strip():
    print("  불일치 openAiPrompt"); ok = False
print("설정 검증:", "통과" if ok else "실패")

# 타겟에 **실제로 심은** 값의 지문을 남긴다 (D-058 / CANARY_DESIGN 3-2).
# scripts/verify_gateway.sh가 .env 지문 · health 지문과 셋을 대조한다.
#
# .env ↔ 게이트웨이만 대조하면 "setup을 돌린 뒤 .env를 바꾼 경우"를 못 잡는다.
# 그때 타겟엔 옛 값, 게이트웨이엔 새 값이 있고 검출률이 조용히 0이 되는데,
# 값이 있긴 하므로 게이트웨이의 fail-loud(R3)가 안 걸린다. 이 파일이 그 구멍이다.
#
# **검증 실패해도 파일을 남긴다.** 안 남기면 직전 실행의 낡은 파일이 그대로 남아
# verify가 옛 지문과 대조하게 되고, 그게 지금 막으려는 사고와 같은 종류다.
# 대신 status를 적고 verify가 status=ok가 아니면 거부한다.
FP_PATH = pathlib.Path("results/target_canary_fp.txt")
FP_PATH.parent.mkdir(parents=True, exist_ok=True)
FP_PATH.write_text("\n".join([
    f"ts={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
    f"status={'ok' if ok else 'fail'}",
    f"slug={SLUG}",
    f"canary_a={canary_fingerprint(os.environ['CANARY_A_TOKEN'])}",
    f"canary_b={canary_fingerprint(os.environ['CANARY_B_TOKEN'])}",
    f"canary_doc={canary_fingerprint(tok)}",
]) + "\n", encoding="utf-8")
print(f"카나리 지문 기록: {FP_PATH}  (값이 아니라 지문이다)")

sys.exit(0 if ok else 1)
