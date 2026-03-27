---
name: run-tests
description: 프로젝트 테스트 실행 및 결과 분석. /test로 pytest와 ruff를 실행하고 실패를 분석.
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
---

# Test Runner

실행 시:

1. 테스트 실행:
   ```bash
   cd /Users/bokyung/onboarding-agent && uv run pytest -v --tb=short 2>&1
   ```

2. 모든 테스트 통과 시 요약 보고.

3. 테스트 실패 시:
   - 실패한 테스트 파일과 대상 소스 파일을 읽는다.
   - 각 실패의 근본 원인을 파악한다.
   - 요약: 테스트명, 에러, 원인, 수정 제안.
   - 사용자에게 수정 적용 여부를 물어본다.

4. 테스트가 없으면 `app/`의 기존 소스를 기반으로 초기 테스트 생성을 제안한다.

5. 린트 실행:
   ```bash
   cd /Users/bokyung/onboarding-agent && uv run ruff check . 2>&1
   ```

6. 린트 이슈가 있으면 테스트 결과와 함께 보고.
