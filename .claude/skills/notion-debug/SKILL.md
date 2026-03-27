---
name: notion-debug
description: 노션 API 연동 문제 디버깅. /notion-debug로 API 호출 실패, 권한 문제, 연결 오류를 체계적으로 진단.
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash
agent: notion-specialist
---

# Notion API Debugger

실행 시 노션 API 문제를 체계적으로 진단한다.

## 진단 단계

1. **환경 확인**: `NOTION_API_KEY`, `NOTION_ROOT_PAGE_ID` 설정 확인 (값 출력 금지).
   ```bash
   python -c "import os; print('API key set:', bool(os.environ.get('NOTION_API_KEY'))); print('Root page set:', bool(os.environ.get('NOTION_ROOT_PAGE_ID')))"
   ```

2. **연결 테스트**: 기본 API 호출로 토큰 유효성 확인.
   ```bash
   cd /Users/bokyung/onboarding-agent && uv run python -c "
   import asyncio, os
   from notion_client import AsyncClient
   async def test():
       client = AsyncClient(auth=os.environ['NOTION_API_KEY'])
       try:
           user = await client.users.me()
           print('Connected as:', user.get('name', 'integration'))
       except Exception as e:
           print('Connection failed:', e)
   asyncio.run(test())
   "
   ```

3. **페이지 접근 테스트**: 루트 페이지 읽기 가능 여부 확인.

4. **코드 분석**: `app/services/notion.py`에서 에러 핸들링 패턴 검토.

5. **Rate limit 확인**: 재시도 로직 유무 확인. 없으면 플래그.

6. **진단 보고**: 구체적 수정 방안과 함께 진단 결과 제시.

## 자주 발생하는 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| 401 Unauthorized | 잘못된 토큰 | 노션 통합 설정에서 재생성 |
| 403 Forbidden | 페이지 접근 권한 없음 | 노션에서 통합에 페이지 공유 |
| 빈 검색 결과 | 인덱싱 미완 또는 범위 오류 | 30초 대기 또는 parent 필터 확인 |
| 타임아웃 | 블록이 많은 대형 페이지 | 페이지네이션 + 타임아웃 처리 추가 |
