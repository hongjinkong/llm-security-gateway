# D-062 검증 기록 — 2026-09-22

Python: 3.14.7. GPU·타겟 미사용. 합성 자료와 기존 리포트만 사용.

## 재현 명령

```bash
python3 -m pytest tests/test_cluster_ci.py -q
python3 scripts/mutate_cluster_ci.py
PYTHONHASHSEED=1 python3 scripts/cluster_ci.py --base results/pi_base.report.jsonl --rule results/pi_rule.report.jsonl > /tmp/cluster-1.md
PYTHONHASHSEED=2 python3 scripts/cluster_ci.py --base results/pi_base.report.jsonl --rule results/pi_rule.report.jsonl > /tmp/cluster-2.md
cmp /tmp/cluster-1.md /tmp/cluster-2.md
```

두 실제 실행 모두 exit=0, 파일 바이트 일치. C1 정수쌍 6개 일치,
C2 양쪽 435군집·768 attempt·7,680 출력, C3 여섯 비율 모두 통과,
C4 두 극단 통과. 합성 JSONL을 collect → clusters → bootstrap으로 읽는 별도 테스트도 통과.

## 실제 변이 실행

최종 전체 회귀 검증: `python3 -m pytest -q` → **433 passed** (19.55s).
로컬 포트를 사용하는 통합 테스트까지 포함한다.

임시 디렉터리에 복사한 코드에 하나씩 주입. 각 지정 테스트는 기준선에서 통과하고,
변이 후 assertion으로 실패했다. 실행 오류·수집 오류는 검출로 인정하지 않는다.

```text
기준선: 21 passed
M1 출력 단위 재표집: 검출 — test_c4_rho1_폭이_Wilson의_루트10배_안팎이다
M2 비복원추출: 검출 — test_변이2_CI_폭이_0이_아니다
M3 군집 고정 후 군집 내부만 재표집: 검출 — test_c4_rho1_폭이_Wilson의_루트10배_안팎이다
M4 percentile 상하한 뒤바꿈: 검출 — test_변이4_하한이_상한보다_크지_않다
M5 짝 깨기: 검출 — test_변이5_짝지은_차이는_상수차이_자료에서_폭이_거의_0이다
M6 이름 정규화 누락: 검출 — test_변이6_제너레이터_이름을_정규화해야_두_팔이_짝지어진다
M7 B=10: 검출 — test_변이7_B가_충분하면_다른_seed에서도_경계가_거의_같다
7/7 검출. 원본 파일 무수정.
```

## 산출물 SHA-256

```text
b7ba0d2a694269faff833d0aecd2c0141a2370f99a304c0f8e7effc12b12d2c1  results/pi_base.report.jsonl
7f9a3e16f1c61d4e72065622ccb185358b6a8475e37acb2864f2abdb4860d8cd  results/pi_rule.report.jsonl
dbb89854cd463e083cfd69c6f5f2b5b304928050d52973cae79ac45c661d1a20  scripts/cluster_ci.py
5c5783d61baab43fe548f4b7f87c5a4f2f7b3b341da5df36990982c5e34c78a7  scripts/mutate_cluster_ci.py
b5d38db92220d2e458fd45cd4ebf5bddab12390c786b9f183dd0cba7747b28ca  tests/test_cluster_ci.py
51cc314e77bd76685033f58be3eea61445667d2b549288ab252d991dd4eb04d3  results/cluster_ci_pi_20260922.md
```
