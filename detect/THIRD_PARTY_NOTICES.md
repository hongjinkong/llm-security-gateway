# 탐지 사이드카 이미지에 든 모델과 라이선스

탐지 사이드카 이미지(`detect/Dockerfile`)는 빌드할 때 아래 모델 파일을 Hugging Face의 고정 리비전에서 받아 `/models/<이름>/`에 둔다(리비전과 파일 SHA-256은 `detect/models.json`).
모델은 각 제작자의 저작물이고, 이 저장소의 코드(Apache-2.0)와 따로 라이선스된다. 이미지 안에서 이 파일은 `/licenses/THIRD_PARTY_NOTICES.md`, Apache-2.0 본문은 `/licenses/LICENSE`다.

| 이미지의 이름 | 출처(리비전) | 라이선스 | 이미지 안의 고지 |
|---|---|---|---|
| `veil-ko-lite-int8` (한국어 이름·주소 인식) | [`1T/veil-pii-ko-lite`](https://huggingface.co/1T/veil-pii-ko-lite) @ `a8343030ef774ad78d6f0481a6877a971cef759d` | Apache-2.0(모델 카드의 표시) | 제작자 저장소에 LICENSE·NOTICE 파일이 없다 — 본문은 `/licenses/LICENSE` |
| `horizon-guard-base-int8` (인젝션 분류기 — 기본으로 싣지 않는다) | [`Horizon-Labs/prompt-injection-guard-base`](https://huggingface.co/Horizon-Labs/prompt-injection-guard-base) @ `8c321b08c01102a0a3a377f8eecda0cab80e8758` | Apache-2.0 | 제작자의 `/models/horizon-guard-base-int8/LICENSE`·`NOTICE`(바탕 모델 mmBERT의 MIT 고지 포함) |

모델 파일은 고치지 않고 그대로 싣는다. `--build-arg MODEL=…`·`INJECTION_MODEL=…`로 다른 모델을 넣어 빌드해 배포하면 그 모델의 라이선스 고지를 이 표에 더한다.
