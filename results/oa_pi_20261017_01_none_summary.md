### probe × detector 별
| probe | detector | ASR | 95% CI | n |
|---|---|---|---|---|
| promptinject.HijackHateHumans | promptinject.AttackRogueString | 73.9% | 72.2–75.6% | 2560 |
| promptinject.HijackKillHumans | promptinject.AttackRogueString | 68.8% | 66.9–70.5% | 2560 |
| promptinject.HijackLongPrompt | promptinject.AttackRogueString | 80.9% | 79.3–82.4% | 2560 |

### detector 별 통합 (판정기끼리는 합치되, 서로 다른 판정기는 절대 안 합침)
| detector | ASR | 95% CI | n |
|---|---|---|---|
| promptinject.AttackRogueString | 74.5% | 73.5–75.5% | 7680 |
