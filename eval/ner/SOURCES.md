# NER 평가셋 출처(D-125)

| 파일 | 출처 | 라이선스 | 바꾼 것 |
|---|---|---|---|
| `synth.jsonl` | 이 저장소(`make_synth.py`, 시드 20261101) — 템플릿 35개·성씨·이름·주소·기관 사전 | 본 저장소(Apache-2.0) | — |
| `kdpii_test.jsonl` | KDPII test → `1T/veil-pii-ko-stress` `leakage/kdpii_test_dedup.jsonl` @`1a3106d85d5bfd3851128ce14535a27038f051a4` | CC BY 4.0 | 아래 |

## KDPII

- KDPII(Korean Dialogue PII) — 연세대학교 김한샘 연구실·TSCIENTIFIC Co., Ltd.(Zenodo 기록의 작성자: Kim Hansaem, Li Fei, Kang Yejee, Park Seoyoon 외), IEEE Access 2024.
  데이터: Zenodo, doi:[10.5281/zenodo.10968609](https://doi.org/10.5281/zenodo.10968609).
- 라이선스: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

## 1T/veil-pii-ko-stress

- Wontae Kim, <https://huggingface.co/datasets/1T/veil-pii-ko-stress> — KDPII test에서 train과 텍스트가 완전히 같은 92행을 뺀 4,799행을 문자 위치 구간으로 옮기고,
  KDPII 라벨을 그 저장소의 32종 스키마로 바꿨다(PS_NAME·PS_NICKNAME → PERSON, LC_ADDRESS·LC_PLACE → ADDRESS, OG_WORKPLACE·OG_DEPARTMENT·OGG_EDUCATION·OGG_CLUB·
  CV_MILITARY_CAMP → ORGANIZATION 등). 라이선스: CC BY 4.0.

## 이 저장소에서 바꾼 것(`build_kdpii.py`)

- 원본 파일의 SHA-256 `2567966e4dd3452ec2994090a3b5a085314c056cf4df5ed4b3d57ab31150023d`을 확인한 뒤, PERSON·ADDRESS·ORGANIZATION 구간만 `person`·`address`·`org`로 남기고
  나머지 구간과 `lang`·`source`·`aug`·`valid`·`bad` 필드를 뺐다. 행과 순서·텍스트는 그대로다.
- 이 셋의 규약은 넓다 — 나라·도시·역·가게 이름도 주소, 별명·성만 쓴 호칭도 이름, 학과·동아리·군부대도 직장이고, 주소는 구성 요소마다 따로 단다.
  그래서 채점은 모델 라벨을 이 규약으로 옮기는 대응(`detect/models.json`의 `kinds_kdpii`)으로, 주소 잇기를 끄고 한다(D-125 §2-4).
