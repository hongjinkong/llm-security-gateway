### probe × detector 별
| probe | detector | ASR | 95% CI | n |
|---|---|---|---|---|
| promptinject.HijackHateHumans | promptinject.AttackRogueString | 70.2% | 68.4–71.9% | 2560 |
| promptinject.HijackKillHumans | promptinject.AttackRogueString | 64.9% | 63.1–66.7% | 2560 |
| promptinject.HijackLongPrompt | promptinject.AttackRogueString | 81.4% | 79.9–82.9% | 2560 |

### detector 별 통합 (판정기끼리는 합치되, 서로 다른 판정기는 절대 안 합침)
| detector | ASR | 95% CI | n |
|---|---|---|---|
| promptinject.AttackRogueString | 72.2% | 71.2–73.2% | 7680 |
