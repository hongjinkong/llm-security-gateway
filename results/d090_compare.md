# D-090 S2 비교 — DanInTheWild 표집 재현

- M `results/oa_dan_20260930_01_none.report.jsonl`, N `results/oa_dan_20261006_01_none.report.jsonl`, 프롬프트 256개
- M과 N이 다른 seq 8개: [241, 242, 246, 247, 250, 253, 254, 255]

| 재현 | 파일 | 수 | M 일치 | N 일치 | jitter 대기값 |
|---|---|---|---|---|---|
| A1 | `results/d090_replay_A_1.json` | 256 | 256/256 | 248/256 | None |
| A2 | `results/d090_replay_A_2.json` | 256 | 256/256 | 248/256 | None |
| B1 | `results/d090_replay_B_1.json` | 256 | 248/256 | 256/256 | 0.5359501982792404 |
| B2 | `results/d090_replay_B_2.json` | 256 | 248/256 | 256/256 | 0.5359501982792404 |

- garak_version: "0.15.1"
- backoff_version: "2.2.1"
- python: "3.12.13"
- soft_probe_prompt_cap: 256
- data_sha256: "2e3496db26bab605498357a8670523bbca07a14438eee5a4c79e6a32968c1875"
- data_items: 666
- data_items_nonempty: 666
- generator_name: "target-anythingllm"
- formatted_count: 0
- trace: ["seed", "hint", "probes.dan.Ablation_Dan_11_0", "probes.dan.AntiDAN", "probes.dan.AutoDANCached", "probes.dan.ChatGPT_Developer_Mode_RANTI", "backoff", "probes.dan.ChatGPT_Developer_Mode_v2", "probes.dan.ChatGPT_Image_Markdown", "probes.dan.DAN_Jailbreak", "probes.dan.DUDE", "probes.dan.DanInTheWild"] / ["seed", "hint", "probes.dan.Ablation_Dan_11_0", "probes.dan.AntiDAN", "probes.dan.AutoDANCached", "probes.dan.ChatGPT_Developer_Mode_RANTI", "probes.dan.ChatGPT_Developer_Mode_v2", "probes.dan.ChatGPT_Image_Markdown", "probes.dan.DAN_Jailbreak", "probes.dan.DUDE", "probes.dan.DanInTheWild"]

- 보조 관찰(판정에 쓰지 않음): 변형 B jitter [0.5359501982792404, 0.5359501982792404], 모두 0.45 이상 0.55 미만: 예

**S2: H1과 일치 — 최종 'H1 확인'은 S1 일치가 함께 필요하다**
