# 인젝션 분류기 학습 데이터 — 출처·라이선스 (D-128, PLAN 18-1단계)

`build.py`가 만드는 `train.jsonl`·`val.jsonl`의 출처·고정 리비전·라이선스·쓴 행·바꾼 것을 적는다. 평가셋(`../SOURCES.md`)과 같은 스키마·같은 규칙이고, 아래는 **학습에만** 더한 것과 평가셋 출처의 남은 행이다.
학습 행은 평가 그룹(dev-eval·홀드아웃)과 그룹을 공유하지 않고 정규화 문장이 평가셋의 어느 행과도 같지 않다(`tests/test_d128_train.py` T1). 공격을 LLM으로 만들거나 번역하지 않았고, 어떤 공격문도 LLM API로 보내지 않았다.
원문 텍스트는 이 문서에 넣지 않는다. 행수는 2026-11-04 빌드의 `train.jsonl`+`val.jsonl` 합계(변형·꼬리 포함)다 — 정확한 수는 `python3 eval/injection/train/build.py`의 요약.

- datasets-server로 받는 출처(neuralchemy·gandalf)의 받은 날짜: **2026-11-04**(리비전 고정 불가 — 받은 결과를 저장소에 고정, SHA-256은 DECISIONS D-128 §6과 테스트에)
- 분할 규칙(`split.py`): dev 그룹의 SHA-256(`"d128\x1f" + group`) 첫 바이트 < 128 → 학습 쪽(dev-train) · 학습 그룹의 SHA-256(`"val\x1f" + group`) 첫 바이트 < 26 → `val.jsonl`

## 평가셋(dev)의 학습 쪽 절반 — `../SOURCES.md`의 출처 그대로

dev 5,492행 중 학습 쪽 그룹의 행(다중 턴 `ctf-satml24`는 뺀다 — 턴마다 라벨이 없다). 출처별 라이선스·고지는 평가셋 문서를 따른다. 학습 쪽에 든 출처: corpus·corpus_xform(본 저장소), korean_guardrail_test·KoreanGuardrail·drakkeng(CC-BY-4.0),
JHC56(BSD-2-Clause + Apache-2.0), guardrail4agent·deepset(Apache-2.0), service_query_gating·gandalf·PurpleLlama·BIPIA·InjecAgent·NotInject(MIT), all100·agent_ko(본 저장소).

## 평가셋 출처의 남은 행(평가셋이 표본만 쓴 것)

### `tristan-kim/guardrail4agent-sft` @bd89cc6b — Apache-2.0
- S3(도구 결과 속 간접 인젝션, 1,200바이트 이하)·S5(시스템 프롬프트 추출)·safe 가운데 평가셋이 뽑지 않은 행 전부(S3·S5)와 safe 표본 900. 평가셋과 같은 id 규칙(`g4a-<라벨>-<행번호>`)·매핑. 쓴 행(변형·꼬리 포함): 공격 2,363 · 정상 949.

### `taeyun16/korean-service-query-gating-v1` @9f0cc771 — MIT
- 평가 그룹(`split_group`)에 없는 행에서 표본 500(정상, 트리거 어휘가 있으면 hard_negative). 쓴 행: 정상 613(변형·꼬리 포함).

### `kimchunsik03/KoreanGuardrail` @cd4c93cb — CC-BY-4.0
- `benchmark.jsonl`에서 **씨앗이 학습 쪽인 그룹**의 난독화 변형만(`clean` 제외, 모든 강도) — 공격 표본 700(`encoding`, `transform`=기법), **정상 씨앗의 난독화 행** 표본 400(`hard_negative`, 평가셋이 쓰지 않은 행). 평가셋이 쓴 강도 1.0 공격 표본은 문장 겹침 제거로 빠진다.
- 바꾼 것(CC-BY): 원문 무변경, 스키마 태깅·표본 선택만. 라이선스: https://creativecommons.org/licenses/by/4.0/

### `Lakera/gandalf_ignore_instructions` — MIT(datasets-server, 받은 날짜 2026-11-04)
- 남은 영어 공격 표본 350 중 평가셋과 겹치지 않은 229(기준 모델이 학습한 셋 — 되풀이 데이터로만). 선택 편향('ignore' 문구)은 평가셋 문서와 같다.

## 학습에만 더한 공개 출처

### `neuralchemy/Prompt-injection-dataset` core/train — Apache-2.0(datasets-server, 받은 날짜 2026-11-04)
- URL: https://huggingface.co/datasets/neuralchemy/Prompt-injection-dataset · 기준 모델(Horizon guard)이 학습한 영어 셋 — 원래 실력을 지키는 되풀이 데이터. 저작권자: neuralchemy.
- 쓴 행: 공격 표본 700·정상 표본 500(변형·꼬리 포함 1,229·600). `label` 1→`category`로 유형(indirect_injection→`indirect`·role tool, encoding_obfuscation·token_smuggling→`encoding`, 나머지→`direct`), 0→`benign`(트리거 어휘면 `hard_negative`). `group`=`nc-<group_id>`(출처의 증강 가족), id=`nc-<행번호>`.

### `S-Labs/prompt-injection-dataset` @002a9dd1 — MIT
- URL: https://huggingface.co/datasets/S-Labs/prompt-injection-dataset (`data/train.csv`) · 기준 모델이 학습한 영어 셋(LLM 합성, 하드 네거티브 포함). 저작권자: S-Labs.
- 쓴 행: 공격 표본 600·정상 표본 600(변형·꼬리 포함 1,064·738). label 1→`direct`, 0→`benign`/`hard_negative`. `group`=행마다.

### `yanismiraoui/prompt_injections` @bd55359f — Apache-2.0
- URL: https://huggingface.co/datasets/yanismiraoui/prompt_injections (`prompt_injections.csv`, 1,034행 — 영·프·독·스·포·이·루마니아어) · 기준 모델이 학습한 다국어 공격 셋. 저작권자: Yanis Miraoui. 고지(NOTICE)는 출처 저장소에 있다.
- 쓴 행: 공격 표본 300(변형·꼬리 포함 537). 전부 `direct`, `lang`은 휴리스틱(en·other).

### `Gyr0ghost/promptwall-injection-dataset` @2d6532ef — MIT
- URL: https://huggingface.co/datasets/Gyr0ghost/promptwall-injection-dataset (`attacks.jsonl` 430·`safe.jsonl` 70, 10여 언어 — 한국어 공격 4). 저작권자: Himanshu Choubey (PromptWall).
- 쓴 행: 공격 430·정상 70(변형·꼬리 포함 728·76). `attack_type` indirect_injection→`indirect`, encoded_attack→`encoding`, 나머지(direct_injection·jailbreak·prompt_exfiltration·social_engineering·persona_hijacking·multi_turn_drift)→`direct`; safe→`benign`.

### 에이전트 작성(이 단계) — 본 저장소, `benign_ko_train.jsonl`(`agent_ko_train`)
- 한국어 **정상 문장만**(D-123 규칙 — 공격은 쓰지 않는다): 작성자 4(HR·총무·재무 / 고객지원·전자상거래·물류 / 개발·IT 운영·보안 / 교육·공공·의료·법률·부동산·여행, 각 150줄 — benign 70·hard_negative 80, 문서 발췌는 role tool)와
  작성 파일마다 검증자 2(보안 관점 — 숨은 지시·가짜 역할 머리·실제 개인정보 / 자료 품질 — 어색한 문장·중복·트리거 어휘 없음)가 따로 읽어 하나라도 뺀 줄은 뺐다. id는 문장 해시(`ko-train-<작성자>-<sha10>`)라 다시 만들어도 같다. 가상의 이름·회사만.
- 쓴 행: 600줄 중 검증자가 56줄을 빼고(보안 1·품질 55) 한국어가 아닌 1줄을 빼 543행(benign 278·hard_negative 265, 문서 발췌 126) — 변형·꼬리 포함 646. 평가셋의 에이전트 문장(`agent_ko`)과 같은 문장은 문장 겹침 제거가 뺀다(이번 빌드 0).

## 결정적 변형·판정 조작 꼬리(본 저장소, `build.py`)

- **변형**(`transform`): 평가셋의 5종(synonym·spacing·fullwidth·zero_width·base64 — `eval/injection/build.py`의 같은 함수) + `jamo`(음절→호환 자모)·`chosung`(초성만). 공격(direct·indirect·role_spoof)의 절반(id 해시)에 하나씩(한국어가 아니면 jamo·chosung·synonym 대신 zero_width) → `encoding`,
  정상의 1/8에 spacing·fullwidth·zero_width·jamo 가운데 하나 → `hard_negative`. 이미 난독화된 행에는 씌우지 않는다. 그룹은 바탕 행과 같다.
- **꼬리**(`transform`=`tail:<이름>`) 12종 — 한국어 6(가짜 분류 JSON·보안팀 검토 완료·교육용 예문·검수 완료 머리·필터 끄기·판단 메모)·영어 6(classifier 주석·moderation note·training material·status 줄·approved 머리·ticket 메모).
  공격의 1/4에 씌워 label 1(유형 그대로), 정상의 1/12에 씌워 label 0(`hard_negative`). **D-054의 6문구(`detect/evaluate_injection.py` PAYLOADS)와 다른 문구**이고 그 문구는 학습에 없다(T2) — 양성대조로만 쓴다.

## 뺀 것

`Necent/llm-jailbreak-prompt-injection-dataset`(MIT이지만 승인 게이트·원출처와 번역 품질 불명), `prismdata/guardrail-ko-11class-dataset`(GPL-3.0), `MarkrAI/ko-jailbreak`(평가셋 문서의 사유 그대로), XL-SafetyBench·Nemotron-Safety-Guard(유해 요청 — 인젝션 아님),
`ctf-satml24` 다중 턴(턴마다 라벨이 없다), `wambosec`·`xTRam1`(LLM 합성 전량·라이선스 없음 — 기준 모델도 쓰지 않았다), 평가셋에 쓴 행 전부(문장 겹침 제거).

## 라이선스 고지

Apache-2.0 출처(neuralchemy·yanismiraoui·guardrail4agent)와 CC-BY-4.0 출처(KoreanGuardrail)는 원문을 바꾸지 않았고 바꾼 것(스키마 필드·그룹·표본·중복 제거·결정적 변형과 꼬리를 **새 행**으로 더함)을 위에 적었다. Apache-2.0 전문은 저장소 루트 `LICENSE`.
MIT 출처는 아래 저작권자에 적용된다(라이선스 전문은 `../SOURCES.md`의 MIT 절과 같다):

- Copyright (c) S-Labs — `prompt-injection-dataset`
- Copyright (c) 2025 Himanshu Choubey — `promptwall-injection-dataset`
- Copyright (c) Lakera AI — `gandalf_ignore_instructions`
- Copyright (c) taeyun16 — `korean-service-query-gating-v1`
