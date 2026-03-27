---
name: plan-feature
description: 온보딩 에이전트의 새 기능을 계획한다. /plan-feature로 구조화된 기능 계획을 시작.
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
agent: planner
---

# Feature Planning

실행 시 사용자와 함께 새 기능을 계획한다.

## 프로세스

1. **범위 확인**: 기능이 무엇을 해야 하는지 질문. 구체적 사용 예시 확보.

2. **기존 코드 탐색**: `app/` 디렉토리를 읽어 현재 아키텍처를 파악하고 기능이 들어갈 위치 식별.

3. **계획 작성**:

```
## Feature: {이름}

### 문제
해결하는 사용자 문제

### API 설계
- 엔드포인트: 메서드, 경로, request/response 모델
- 예시 요청/응답 JSON

### 구현 단계
파일별 변경 사항 순서 목록

### 노션 API 영향
새 API 호출, 권한, 데이터

### 테스트 전략
주요 테스트 케이스

### 미결 사항
구현 전 결정 필요 항목
```

4. **사용자 리뷰**: 계획을 제시하고 피드백 반영 후 구현 시작.
