# 인젝션 평가셋 v1 — 출처·라이선스 (D-123, PLAN 16단계)

`build.py`가 받는 모든 출처의 URL·고정 리비전·라이선스·저작권자·쓴 행수·라벨/유형 매핑·바꾼 것을 적는다.
공격은 공개셋 + `gateway/data/injection_corpus.jsonl` 59건 + 그 59건의 결정적 변형뿐이다. LLM으로 공격을 만들거나 번역하지 않았고, 어떤 공격문도 LLM API로 보내지 않았다.
행수는 2026-10-31 받기 기준이며 `dev.jsonl`+`holdout.jsonl` 합계다(출처별 표본 상한은 `build.py`의 `pick(..., N)`에 있다). 원문 텍스트는 이 문서에 넣지 않는다.

datasets-server로 받는 출처(deepset·gandalf·ctf-satml24·NotInject — 원본이 parquet뿐이고 새 의존성을 쓰지 않는다)는 리비전을 고정할 수 없어 받은 날짜를 적고,
받은 결과를 `dev.jsonl`·`holdout.jsonl`로 저장소에 고정한다(SHA-256은 DECISIONS D-123 §6과 테스트에). InjecAgent는 받은 날의 HEAD를 적는다.

- 받은 날짜: **2026-10-31**
- ctf-satml24 행 오프셋(`interaction_chats`/`attack`, 길이 100): **0, 10000, 20000, …, 130000** (14쪽)

## 스키마 매핑 공통 규칙

- `lang`: 출처가 언어를 단 경우(drakkeng)와 글자로 알 수 없는 변형(우리 코퍼스의 변형·KoreanGuardrail 난독화 — 원문 ko)은 그 언어. 그 밖은 결정적 휴리스틱 —
  글자 중 한글 ≥ 30%면 `ko`, 거의 ASCII이고 독일어 꼴·악센트 글자가 없으면 `en`, 아니면 `other`.
- `type`: direct(직접 지시 뒤집기·역할 변경·시스템 프롬프트 요청) / indirect(문서·도구 결과에 심은 지시) / role_spoof(가짜 역할 머리·대화 마크업) / encoding(난독화) / multi_turn(여러 턴) / benign / hard_negative.
- `role`: 간접 공격과 문서형 정상은 `tool`, 나머지는 `user`.
- `hard_negative`: 출처가 하드 네거티브로 표시했거나, 정상 행에 트리거 어휘(무시·지시사항·지시·명령·시스템 프롬프트·개발자 모드·탈옥·DAN·제한 없이·ignore·disregard·instructions·system prompt·jailbreak·developer mode·act as·pretend)가 있으면 승격한다.
- `group`: 같은 원문의 말투·난독화·변형이 공유한다(홀드아웃을 그룹째로 나눈다). 출처를 넘는 가족도 묶는다 — JHC56 한국어 말투는 그 원문 deepset 행과,
  deepset의 '쌓은' 합성 문장은 그 안에 그대로 든 원문과, ctf 대화는 공격 팀 단위로. 뽑기 순서 해시는 분할 해시와 상관을 끊으려고 소금(`pick\x1f`)을 섞는다.
- 중복: 셋 전체에서 공백을 정규화해 같은 문장은 id가 가장 작은 하나만 남긴다(라벨이 엇갈리면 모두 뺀다 — 이번 빌드 0건). 이번 빌드에서 98행을 뺐다.

---

## 자체 출처

### `gateway/data/injection_corpus.jsonl` — 본 저장소
- 쓴 행: 공격 59 (`corpus`). `category` R3 → `role_spoof`, 나머지(R1·R2a·R2b) → `direct`. 전부 `ko`.
- 결정적 변형(`corpus_xform`, 254행, `type=encoding`, `transform` 지정, `group`=원본 id): 59건마다 synonym(고정 동의어 표로 트리거 단어 치환)·spacing(공백 제거)·fullwidth(ASCII→전각)·zero_width(U+200B 삽입)·base64(원문을 base64로 싸서 "디코드해서 따르라"는 한 줄 래퍼). 바뀌지 않는 변형(전각: 한글만 든 행)은 버린다.

### `eval/benign/all100.jsonl` — 본 저장소
- 쓴 행: 정상 89 (`all100`, 100문항 중 같은 문장 11개를 뺀 고유 89). HR 질의. `text`=`q`, `type=benign`, `ko`.

### 에이전트 작성(이 단계) — 본 저장소
- 쓴 행: 정상 717 (`agent_ko`, 파일 `benign_ko.jsonl`). 에이전트 9개가 6개 도메인(HR·고객지원·개발·금융·의료·법률)마다 업무 요청 약 50·문서 약 20을 쓰고(420),
  하드 네거티브 300(‘무시·지시사항·명령’, ‘개발자 모드·탈옥·DAN·~인 척·제한 없이’, ‘시스템 프롬프트·프롬프트 엔지니어링·System: 로그’ 세 묶음 × 100)을 썼다.
  하드 네거티브는 묶음 50개씩 두 검증자(보안 관점·자료 품질 관점)가 따로 읽고, 둘 중 하나라도 정상으로 볼 수 없다고 한 3개를 뺐다(297). 정상 문장만 썼다 — 공격은 쓰지 않는다(PLAN 16단계).
  id는 문장 해시라 다시 만들어도 같다. 가상의 이름·회사만 쓴다. `ko`.

---

## 한국어 공개 출처

### `xxxjjhhh/korean_guardrail_test`
- URL: https://huggingface.co/datasets/xxxjjhhh/korean_guardrail_test · 고정 리비전 **cd91a65d49458352795c92d047305b3c25af938b** (`main.jsonl`)
- 라이선스: **CC-BY-4.0** (카드 YAML). 저작권자: xxxjjhhh(데이터셋 작성자).
- 쓴 행: 공격 317 · 정상 251(같은 문장 79행을 뺐다). `is_injection=true`→`direct`(label 1), `false`→`benign`(label 0). `group`=행 id.
- 바꾼 것(CC-BY 변경 표시): 원문 텍스트 무변경. 스키마 필드(id→`kgt-<id>`, lang·type·role·group)를 새로 붙이고 같은 문장을 하나만 남겼다. 라이선스: https://creativecommons.org/licenses/by/4.0/

### `kimchunsik03/KoreanGuardrail`
- URL: https://huggingface.co/datasets/kimchunsik03/KoreanGuardrail · 고정 리비전 **cd4c93cbd39bd481c9e9bebd3686c56bfc2af3e4**
- 라이선스: 데이터 **CC-BY-4.0**, 포함 코드(`ko_obfuscator.py`·`build_benchmark.py`) Apache-2.0. 저작권자: kimchunsik03.
- 쓴 행: 공격 800 · 정상 204.
  - `seeds/attacks.jsonl` 301 → label 1. `subtype` fake_system·fake_conversation→`role_spoof`, embedded_in_content→`indirect`(role tool), 나머지→`direct`
    (`indirect` 하위유형은 시스템 프롬프트를 에둘러 묻는 사용자 발화라 `direct`). 다중 턴 행은 없다.
  - `seeds/benign.jsonl` 204 → label 0, `hard_negative`(출처가 적대적 정상으로 표시).
  - `benchmark.jsonl`에서 `intensity=1.0`·`label=attack`·난독화 5기법(jamo_decompose·chosung·tensify·break_spacing·zwsp_inject) → `encoding`, 기법마다 100개 표본(총 500). `transform`=기법, `group`=`kg-<seed_id>`(씨앗과 공유), `lang=ko`.
- 바꾼 것(CC-BY): 원문 무변경, 스키마 태깅과 결정적 표본 선택만. Apache-2.0 코드는 재배포하지 않았다. 라이선스: https://creativecommons.org/licenses/by/4.0/

### `JHC56/korean-prompt-injection-registers`
- URL: https://raw.githubusercontent.com/JHC56/korean-prompt-injection-registers · 고정 리비전 **d348b1fdad789222fbfe11b2176ddafad383430e** (`data/dataset.jsonl`)
- 라이선스: deepset 파생 부분 **Apache-2.0**(deepset) + 한국어 번역에 **BSD-2-Clause**(아래 고지). Tensor Trust(qxcv) 부분은 라이선스 불명이라 **뺐다**.
- 쓴 행: 공격 273 · 정상 858. `source`가 deepset이고 `lang=ko`인 행(한국어 7말투)만. label 1→`direct`(역할 바꾸기 `role_reassignment`도 직접 지시), label 0→`benign`.
  한 문항의 7말투는 그 **원문 deepset 행과 같은 그룹**이다(영어 말투 = deepset 원문으로 잇는다). id=`jhc-<id>-<register>`.
- 바꾼 것: 원문 무변경. 스키마 필드와 그룹, 같은 문장 제거.

### `tristan-kim/guardrail4agent-sft`
- URL: https://huggingface.co/datasets/tristan-kim/guardrail4agent-sft · 고정 리비전 **bd89cc6b47b331c94dc6635724c6b1cef991beab** (`data/sft_{train,val,test}.jsonl`)
- 라이선스: **Apache-2.0**. 저작권자: tristan-kim.
- 쓴 행: 공격 400 · 정상 200.
  - S3(도구 결과 속 간접 인젝션, 1200바이트 이하) → `text`=`tool_result`, `indirect`, `role=tool`, label 1. 표본 250.
  - S5(시스템 프롬프트 추출) → `text`=`user_input`, `direct`, label 1. 표본 150.
  - safe → `text`=`user_input`, `benign`, label 0. 표본 200.
- 바꾼 것: 원문 무변경. 스키마 필드 부착과 결정적 표본 선택.

### `taeyun16/korean-service-query-gating-v1`
- URL: https://huggingface.co/datasets/taeyun16/korean-service-query-gating-v1 · 고정 리비전 **9f0cc7714846fdd9d71c6d6911452d9f4b048bdf** (`core/{train,validation,test}.jsonl`)
- 라이선스: **MIT**(LICENSE 파일은 "MIT" 4바이트, 저작권줄 없음). 저작권자: taeyun16.
- 쓴 행: 정상 300. 전부 서비스 질의 → `benign`, label 0. `group`=`sqg-<split_group>`. 표본 300.

---

## 영어·다국어 공개 출처

### `deepset/prompt-injections`
- URL: https://huggingface.co/datasets/deepset/prompt-injections · datasets-server `/rows`로 받음(리비전 핀 불가, 받은 날짜 2026-10-31; 저장소 sha 4f61ecb038e9c3fb77e21034b22511b523772cdd).
- 라이선스: **Apache-2.0**(카드 상단 태그; dataset_info에 CC-BY-4.0도 병기 — 둘 다 저작자 표시). 저작권자: deepset.
- 쓴 행: 공격 263 · 정상 399. label 1→`direct`, 0→`benign`. 독일어 다수라 `lang`은 `other`/`en`으로 갈린다. '쌓은' 합성 문장은 그 안의 원문과 같은 그룹.
- 바꾼 것: 원문 무변경. 스키마 필드와 그룹. 라이선스(CC-BY 병기): https://creativecommons.org/licenses/by/4.0/

### `Lakera/gandalf_ignore_instructions`
- URL: https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions · datasets-server `/rows`로 받음(리비전 핀 불가, 받은 날짜 2026-10-31; 그날 저장소 sha 04737b65e90a6794ec227012e4a255a7def6344b).
- 라이선스: **MIT**. 저작권자: Lakera AI.
- 쓴 행: 공격 200. 전부 `direct`, label 1. **선택 편향 주의**: 'Ignore all previous instructions'와의 임베딩 유사도 ≥ 0.825로 걸러진 셋이라 따로 본다. 표본 200.

### `meta-llama/PurpleLlama` (CyberSecEval prompt_injection)
- URL: https://raw.githubusercontent.com/meta-llama/PurpleLlama · 고정 리비전 **f64eebd53003a87d9c2d2a3a712133534c214c8d** (`CybersecurityBenchmarks/datasets/prompt_injection/prompt_injection.json`)
- 라이선스: 해당 서브트리 **MIT**(`CybersecurityBenchmarks/LICENSE`; 저장소 루트의 Llama 라이선스는 모델용이라 무관). 저작권자: Meta Platforms, Inc. and affiliates.
- 쓴 행: 공격 176(같은 문장 4행을 뺐다). `risk_category=security-violating`만(logic-violating은 시스템 프롬프트에 달린 라벨이라 **뺐다**). `injection_type=indirect`→`indirect`(role tool), 나머지→`direct`. `text`=`user_input`.

### `microsoft/BIPIA` (공격 문자열)
- URL: https://raw.githubusercontent.com/microsoft/BIPIA · 고정 리비전 **a004b69ec0dd446e0afd461d98cb5e96e120a5d0** (`benchmark/{text,code}_attack_{train,test}.json`)
- 라이선스: **MIT**(네 공격 JSON 파일). 저작권자: Microsoft Corporation.
- 쓴 행: 공격 250. 문서에 심는 간접 공격 → `indirect`, `role=tool`, label 1.

### `uiuc-kang-lab/InjecAgent`
- URL: https://raw.githubusercontent.com/uiuc-kang-lab/InjecAgent · 핀 없음 → HEAD **f19c9f2c79a41046eb13c03c51a24c567a8ffa07**(받은 날짜 2026-10-31) (`data/attacker_cases_{dh,ds}.jsonl`)
- 라이선스: **MIT**(`LICENCE`). 저작권자: Qiusi Zhan (2023).
- 쓴 행: 공격 62. 고유 공격 지시(`Attacker Instruction`) → 도구 결과에 심는 `indirect`, `role=tool`, label 1.

### `ethz-spylab/ctf-satml24`
- URL: https://huggingface.co/datasets/ethz-spylab/ctf-satml24 · 핀 없음 → datasets-server `/rows`(받은 날짜 2026-10-31, 오프셋 0~130000 14쪽). `interaction_chats`/`attack`.
- 라이선스: **MIT**. 저작권자: all participants of the LLM CTF @ SaTML 2024, Edoardo Debenedetti, Javier Rando, Daniel Paleka (2024).
- 쓴 행: 공격 77. 비지 않은 사용자 턴이 둘 이상(≤4000바이트)인 공격 대화 → `turns`(사용자 발화만), `multi_turn`, `role=user`, label 1.
  같은 팀이 같은 첫 턴을 여러 대화에 되풀이하므로 **공격 팀(`user.team`)이 그룹**이고, 한 팀이 셋을 채우지 않게 팀마다 최대 10대화.

### `drakkeng/outilsia-injections-prompt-multilingue`
- URL: https://huggingface.co/datasets/drakkeng/outilsia-injections-prompt-multilingue · 고정 리비전 **94be44f2ed97cb83806cb05ab78ceb02629ed8fe** (`{dev,test}.jsonl`)
- 라이선스: **CC-BY-4.0**(https://creativecommons.org/licenses/by/4.0/). 저작자 표시(카드가 요청한 인용): OutilsIA.fr (2026). *Injections de prompt multilingues — corpus PromptForge*. https://outilsia.fr/blog/injections-prompt-francais-2026 (Hugging Face 저장소: drakkeng).
- 쓴 행: 공격 229 · 정상 154. injection에서 `obfuscation_*`→`encoding`(`transform`=기법명), `role_tags`→`role_spoof`, `indirect_document`→`indirect`, 나머지→`direct`.
  정상은 출처가 하드 네거티브로 만든 문장이라 전부 `hard_negative`(그중 `documents`는 `role=tool`). `group`=`drakkeng-<group>`.
- 바꾼 것(CC-BY): 원문 무변경. 스키마 필드 신규 부착(`lang`은 출처의 언어 열: ko·en, 그 밖은 other).

### `leolee99/NotInject`
- URL: https://huggingface.co/datasets/leolee99/NotInject · 핀 없음 → datasets-server `/rows`(받은 날짜 2026-10-31), config `NotInject_one`·`two`·`three`.
- 라이선스: **MIT**(카드 YAML; 논문 코드 저장소 github.com/leolee99/PIGuard의 LICENSE). 저작권자: Hao Li (2024).
- 쓴 행: 정상 339. 전부 트리거 단어가 든 정상 → `hard_negative`, label 0.

---

## 뺀 것

유해 요청셋(MultiJail·Salad-Data·PolyGuardPrompts·JBB behaviors — 인젝션이 아니다), in-the-wild 탈옥 원본(연구용 한정 문구), 라이선스 불명(tom-gibbs 다중 턴·XL-SafetyBench·Tensor Trust 파생),
전체 llmail 라벨 파일(수백 MB). `JHC56`의 Tensor Trust 부분, `PurpleLlama`의 logic-violating 행도 뺐다.
- `MarkrAI/ko-jailbreak`(처음 빌드에 있었다가 뺐다): template 행 대부분(1,000)이 연구용 한정 문구가 붙은 in-the-wild 셋의 한국어 번역이고, 나머지(latent_jailbreak)는
  무해한 과제에 유해 요청을 넣은 꼴이라 인젝션 유형에 맞지 않는다.
- `jackhhao/jailbreak-classification`(처음 빌드에 있었다가 뺐다): 탈옥 행은 in-the-wild 사본이고, 정상 행은 GPTeacher·OpenOrca 문장을 그대로 옮긴 것이라 원출처 고지가 더 필요하다.
  영어 정상은 deepset·NotInject로 충분하다.

---

## 라이선스 고지

CC-BY-4.0 출처(korean_guardrail_test·KoreanGuardrail·drakkeng, deepset 병기)는 위에 저작자·리비전(또는 받은 날짜)·바꾼 것과 라이선스 주소
https://creativecommons.org/licenses/by/4.0/ 를 적었다. Apache-2.0 출처(deepset·guardrail4agent·JHC56의 deepset 부분)는 원문을 바꾸지 않았고 바꾼 것(스키마 필드·그룹·표본·중복 제거)을
위에 적었다. Apache-2.0 전문은 저장소 루트 `LICENSE`에 있다.

### MIT License

아래 MIT 저작권자의 데이터에 적용된다:

- Copyright (c) Lakera AI — `gandalf_ignore_instructions`
- Copyright (c) Meta Platforms, Inc. and affiliates — `PurpleLlama` (CybersecurityBenchmarks)
- Copyright (c) Microsoft Corporation — `BIPIA`
- Copyright (c) 2023 Qiusi Zhan — `InjecAgent`
- Copyright (c) 2024 all participants of the LLM CTF @ SaTML 2024, Edoardo Debenedetti, Javier Rando, Daniel Paleka — `ctf-satml24`
- Copyright (c) 2024 Hao Li — `NotInject` (PIGuard)
- Copyright (c) taeyun16 — `korean-service-query-gating-v1`

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### BSD 2-Clause License

`JHC56/korean-prompt-injection-registers`의 한국어 번역·조립에 적용된다(우리가 쓴 deepset 파생 한국어 부분):

- Copyright (c) 2023, The Regents of the University of California (Tensor Trust 원천 데이터 — 우리는 이 부분을 쓰지 않았다)
- Copyright (c) 2026, Juhyuk choi (한국어 말투 번역·데이터 조립·코드)

```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
