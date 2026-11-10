# 탐지 사이드카 이미지에 든 모델과 라이선스

탐지 사이드카 이미지(`detect/Dockerfile`)는 빌드할 때 아래 모델 파일을 Hugging Face의 고정 리비전에서 받아 `/models/<이름>/`에 둔다(리비전과 파일 SHA-256은 `detect/models.json`).
모델은 각 제작자의 저작물이고, 이 저장소의 코드(Apache-2.0)와 따로 라이선스된다. 이미지 안에서 이 파일은 `/licenses/THIRD_PARTY_NOTICES.md`, Apache-2.0 본문은 `/licenses/LICENSE`다.

| 이미지의 이름 | 출처(리비전) | 라이선스 | 이미지 안의 고지 |
|---|---|---|---|
| `veil-ko-lite-int8` (한국어 이름·주소 인식) | [`1T/veil-pii-ko-lite`](https://huggingface.co/1T/veil-pii-ko-lite) @ `a8343030ef774ad78d6f0481a6877a971cef759d` | Apache-2.0(모델 카드의 표시) | 제작자 저장소에 LICENSE·NOTICE 파일이 없다 — 본문은 `/licenses/LICENSE` |
| `injection-ko-small-int8` (인젝션 분류기 — 기본으로 싣지 않는다) | [`hongjinseon123/llm-gateway-injection-ko-small`](https://huggingface.co/hongjinseon123/llm-gateway-injection-ko-small) @ `78c7a9c6acefb3162258e63b7d958cc8f71ac118` — [`Horizon-Labs/prompt-injection-guard-small`](https://huggingface.co/Horizon-Labs/prompt-injection-guard-small) @ `5ed691c28fc37db51f4e80fb81311b7d2b5d4646`를 이 저장소의 `eval/injection/train/`으로 이어 학습(D-128) | Apache-2.0 | `/models/injection-ko-small-int8/LICENSE`·`NOTICE`(Horizon의 고지·바탕 모델 mmBERT의 MIT 고지·이어 학습 표시). 학습 데이터의 출처·라이선스는 `eval/injection/train/SOURCES.md` |

모델 파일은 고치지 않고 그대로 싣는다. `--build-arg MODEL=…`·`INJECTION_MODEL=…`로 다른 모델을 넣어 빌드해 배포하면 그 모델의 라이선스 고지를 이 표에 더한다.
