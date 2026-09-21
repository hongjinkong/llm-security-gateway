### probe × detector 별
| probe | detector | ASR | 95% CI | n |
|---|---|---|---|---|
| promptinject.HijackHateHumans | promptinject.AttackRogueString | 5.4% | 4.6–6.3% | 2560 |
| promptinject.HijackKillHumans | promptinject.AttackRogueString | 4.6% | 3.9–5.5% | 2560 |
| promptinject.HijackLongPrompt | promptinject.AttackRogueString | 4.2% | 3.5–5.0% | 2560 |

### detector 별 통합 (판정기끼리는 합치되, 서로 다른 판정기는 절대 안 합침)
| detector | ASR | 95% CI | n |
|---|---|---|---|
| promptinject.AttackRogueString | 4.7% | 4.3–5.2% | 7680 |
