# 실 공급자 2턴 확인 — PLAN 7단계 (D-114, 사전 등록 D-111 §6)

질문: 결정적 대체값이 실제 Claude API에서 둘째 턴의 thinking 서명 검사와 프롬프트 캐시를 지키는가. 옛 코드(요청마다 난수 대체값)는 깨뜨리는가.

- 날짜 2026-10-30. 모델 `claude-haiku-5-5`, 비스트리밍, `max_tokens` 1024, effort 기본(medium).
- 모든 요청에 `anthropic-beta: thinking-binding-controls-2026-08-01`과 `thinking: {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "error"}}` —
  계정 생성일과 무관하게 이력 편집 검사를 강제했다. API는 헤더와 필드를 받아들였다(다시 돌 필요 없음).
- 두 팔: **A(옛)** = `research-final`(34c16fb, 코드 지문 `ac56e263ddc6`)을 `git worktree`로 꺼내 띄운 게이트웨이. **B(새)** = main `3bde0db`(지문 `f899df8af20d`).
  같은 상류 키·같은 클라이언트 스크립트([`scripts/check_multiturn_claude.py`](../../scripts/check_multiturn_claude.py)), 둘 다 제품 기본 검사기(injection observe + pii mask).
- 대화: 팔마다 5개 × 2턴(요청 20건), 대화마다 다른 합성 휴대전화·이메일(`@example.com`). system은 합성 환불 규정(`count_tokens` 5,192토큰 — 최소 캐시 길이 512의 10배),
  `cache_control`은 턴 1 user 블록. 턴 2는 게이트웨이가 돌려준 턴 1 `content`(thinking 블록 포함)를 그대로 붙이고 연락처를 다시 적어 달라고 했다.
- 원자료: [`multiturn_claude.jsonl`](multiturn_claude.jsonl) — meta 1줄, 요청 20줄, summary 1줄. 키·합성 원문·답 본문은 없다.

## 결과

| 팔 | 턴 1 (대화 5개) | 턴 2 (대화 5개) |
|---|---|---|
| A 옛 | 200 ×5, 캐시 쓰기 5,447~5,451토큰, thinking 블록 1개씩 | **400 ×5** — ``Invalid `signature` in `thinking` block. The block is bound to a different conversation. … Content before this block differs from when it was created, first at `messages.0.content.0`.`` |
| B 새 | 200 ×5, 캐시 쓰기 5,443~5,447토큰, thinking 블록 1개씩 | **200 ×5**, 캐시 읽기 5,443~5,447토큰(대화마다 턴 1에 쓴 양과 같다), `input_transformations: []`, 복원 2·잔여 0·의심 잔여 0, 답에 원래 전화·이메일 5/5 |

| # | 성공 기준(사전 등록) | 결과 |
|---|---|---|
| P1 | B: 10건 중 400 0건 | **통과** — 0/10 |
| P2 | B: 턴 2 `cache_read_input_tokens > 0`이 5/5 대화 | **통과** — 5/5 |
| P3 | B: 잔여 0, 모델이 되풀이한 원래 값이 사용자 답에 복원 | **통과** — 10건 잔여 0·의심 0, 턴 2 답 5/5에 원래 전화·이메일 |
| P4 | A(양성 대조): 턴 2 400(prefix 불일치) 또는 캐시 읽기 0 | **재현** — 5/5 대화에서 턴 2가 400 |
| P5 | 비용 ≤ $1 | **$0.0130**(요청 20건, usage × 단가 추정. `count_tokens`는 무료) |

## 읽는 법

- A의 400은 사전 등록이 예측한 기제 그대로다. API가 짚은 첫 차이는 `messages.0.content.0`(턴 1 user 블록)이고, 클라이언트는 두 턴에 같은 블록을 보냈다 —
  바뀐 것은 옛 게이트웨이가 요청마다 새로 뽑은 가짜 값뿐이다. 그 블록 뒤에 묶인 thinking 서명이 맞지 않아 둘째 턴 전체가 거절됐다.
- B는 턴 1 user 블록이 같은 바이트로 다시 나가 서명 검사를 통과했고(대화마다 thinking 블록 1개가 실제로 다시 보내졌다 — 검사가 돈 것이다), 턴 1에 쓴 캐시를 턴 2가 그대로 읽었다.
- 이 측정은 `prefix_mismatch_behavior: "error"`로 검사를 강제했다. 그 필드를 넣지 않는 클라이언트는 2026-08-31 이전에 만든 계정이면 400 없이 통과하고(서명 불일치가
  기록만 된다), 그 뒤 계정이면 같은 400을 받는다. 캐시 미스는 계정과 무관하다 — A의 턴 2는 400이 먼저라 캐시 값이 없다.

## 계획과 다르게 된 것

- **턴 1은 10건 모두 `stop_reason: max_tokens`였다.** 출력이 1,024토큰(사전 등록의 `max_tokens`)에서 잘려 답이 회신 초안까지 가지 못했고
  답에 연락처가 없었다(기록은 답 본문을 남기지 않으므로 텍스트가 잘렸는지 아예 없었는지는 모른다) — 턴 1 답의 복원은 시험되지 않았다. 턴 2의 캐시 밖 입력 약 1,096토큰은
  다시 보낸 턴 1 응답(출력 1,024토큰)과 턴 2 질문이다. 서명 검사·캐시라는 이 측정의 질문에는 영향이 없고, 비스트리밍 Messages 응답의 복원은 턴 2에서 5/5 확인됐다. 1,024는 이 과제의 thinking과 답을 함께 담기에 모자랐다 — thinking이 기본으로 켜진
  모델 앞에서 `max_tokens`를 낮게 잡는 클라이언트는 답 없이 끝날 수 있다(게이트웨이와 무관).
