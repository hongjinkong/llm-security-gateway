### probe × detector 별
| probe | detector | ASR | 95% CI | n |
|---|---|---|---|---|
| promptinject.HijackHateHumans | promptinject.AttackRogueString | 73.5% | 71.8–75.2% | 2560 |
| promptinject.HijackKillHumans | promptinject.AttackRogueString | 69.5% | 67.7–71.3% | 2560 |
| promptinject.HijackLongPrompt | promptinject.AttackRogueString | 77.3% | 75.6–78.9% | 2560 |

### detector 별 통합 (판정기끼리는 합치되, 서로 다른 판정기는 절대 안 합침)
| detector | ASR | 95% CI | n |
|---|---|---|---|
| promptinject.AttackRogueString | 73.5% | 72.5–74.4% | 7680 |
