# 보안 정책 · Security Policy

## 제보

취약점은 공개 이슈로 올리지 않는다. GitHub 비공개 제보로 보낸다 — 저장소 **Security → Report a vulnerability**
(<https://github.com/hongjinkong/llm-security-gateway/security/advisories/new>).

- 담을 것: 버전(`/__gateway/info`의 `version`·`code`, 또는 커밋), 재현 절차, 영향. 재현에는 합성 데이터를 쓰고 실제 개인정보·실제 키는 보내지 않는다.
- 확인 회신은 영업일 5일 안을 목표로 한다. 고친 버전은 CHANGELOG와 GitHub 보안 권고에 적고, 제보자가 원하면 이름을 밝힌다.
- 1.0 전에는 가장 최근 릴리스만 보안 수정을 받는다.

## 범위

취약점으로 본다:

- 게이트웨이가 가린다고 문서에 적은 값(README '탐지 종류'의 가림 종류·지원하는 꼴, [API 호환 범위](docs/api-compat.md)의 가리는 자리)이 원문 그대로 상류에 닿는 것
- 감사 로그·지표·오류 응답에 원문이나 키가 남는 것, 다른 요청의 원문이 응답에 섞이는 것
- 인증 우회(게이트웨이 키 없이 중계, 다른 클라이언트의 정책으로 처리), 허용 목록 밖의 경로·헤더가 상류에 닿는 것
- 공급자 키·대체값 키·관리 키가 클라이언트나 로그로 새는 것
- 이미지·배포 견본(`gateway/Dockerfile`, `deploy/`)의 보안 설정 결함

취약점이 아니다(README '막지 못하는 것'에 적은 한계): 지원하지 않는 꼴과 형식 없는 개인정보(이름·주소 등)가 그대로 나가는 것, 감사만 종류,
인젝션 룰을 피하는 문장, 사고 과정(thinking·reasoning)에 보이는 가짜 값, 복원 실패로 사용자가 가짜 값을 받는 것(다른 사람의 원문이 나오면 취약점이다),
문서가 로컬 실험용이라고 적은 설정(`GATEWAY_AUTH=off`, `deploy/compose.yml`의 고정 키).

## English

Do not open public issues for vulnerabilities. Report privately through GitHub: **Security → Report a vulnerability**
(<https://github.com/hongjinkong/llm-security-gateway/security/advisories/new>). Include the version (`version`/`code` from `/__gateway/info`, or a commit),
reproduction steps with synthetic data — never real personal data or real keys — and the impact. We aim to acknowledge within 5 business days.
Before 1.0 only the latest release receives security fixes.

In scope: a value the documentation says is masked reaching the upstream in clear text; raw values or keys in audit logs, metrics or error responses;
another request's original values appearing in a response; authentication bypass or the wrong client policy; paths or headers outside the allow lists reaching the upstream;
leaks of provider, surrogate or admin keys; insecure settings in the image or the deployment samples.
Out of scope: the known limitations in README.en.md "What it does not stop" (unsupported formats, unstructured personal data such as names and addresses, audit-only kinds,
injection-rule bypasses, surrogates visible inside thinking/reasoning, users receiving a surrogate after a restore failure — unless it is someone else's original value),
and settings documented as local-only (`GATEWAY_AUTH=off`, the fixed keys in `deploy/compose.yml`).
