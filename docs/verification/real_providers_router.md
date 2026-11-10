# 실 공급자 확인 2 — 라우터 경유(D-133)

2026-11-10 02:14 UTC · 게이트웨이 코드 6e2881c16420 · 요청 60건 · 상류 MonoRouter. 정상 문장과 합성 값만 보냈다. 답 본문은 기록하지 않는다.

| API | 모델 | 판정 | P1 200만 | P2 가림 | P3 가짜 값 0 | P4 복원 | E | S | T | M |
|---|---|---|---|---|---|---|---|---|---|---|
| chat | `gpt-5.4-mini` | **통과** | ○ | ○ | ○ | ○ | 3/3 | 3/3 | 3/3 | 3/3 |
| chat | `gemini-3.5-flash` | **통과** | ○ | ○ | ○ | ○ | 3/3 | 3/3 | 3/3 | 3/3 |
| chat | `claude-haiku-4.5` | **통과** | ○ | ○ | ○ | ○ | 3/3 | 3/3 | 3/3 | 3/3 |
| responses | `gpt-5.4-mini` | **통과** | ○ | ○ | ○ | ○ | 3/3 | 3/3 | 3/3 | 3/3 |
| messages | `claude-haiku-4.5` | **통과** | ○ | ○ | ○ | ○ | 3/3 | 3/3 | 3/3 | 3/3 |

칸의 숫자는 원래 값이 온전히 돌아온 요청 / 보낸 요청. 건너뛴 조합 없음.
토큰 사용량(감사 줄의 `usage` 합): 입력 8,454 · 출력 4,428. 라우터 잔액 숫자 앞뒤: {'before': {'used_credits': 0, 'reserved_credits': 0, 'prepaid_remaining_credits': 0}, 'after': {'used_credits': 1074, 'reserved_credits': 0, 'prepaid_remaining_credits': 0}}.
