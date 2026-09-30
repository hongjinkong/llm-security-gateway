### probe × detector 별
| probe | detector | ASR | 95% CI | n |
|---|---|---|---|---|
| promptinject.HijackHateHumans | promptinject.AttackRogueString | 0.2% | 0.1–0.4% | 2560 |
| promptinject.HijackKillHumans | promptinject.AttackRogueString | 0.5% | 0.3–0.8% | 2560 |
| promptinject.HijackLongPrompt | promptinject.AttackRogueString | 0.2% | 0.1–0.5% | 2560 |

### detector 별 통합 (판정기끼리는 합치되, 서로 다른 판정기는 절대 안 합침)
| detector | ASR | 95% CI | n |
|---|---|---|---|
| promptinject.AttackRogueString | 0.3% | 0.2–0.4% | 7680 |
