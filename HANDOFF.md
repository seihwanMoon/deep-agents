# Handoff (2026-03-01)

## 오늘까지 진행 상태

- 현재 기준 전체 진행률: **약 68%**
- 백엔드 기준 진행률: **약 75~80%**
- 핵심 미완료 축: **Phase 2 프론트엔드 편집기(/app/agent/[id]/edit)**

세부 근거는 `IMPLEMENTATION_STATUS.md`의 Phase별 평가를 따릅니다.

## 브랜치/커밋 상태

- branch: `work`
- 최신 커밋(이 문서 추가 전): `adbdcf7`
- 테스트 실행 기본 경로: 저장소 루트에서 `pytest -q`

## 내일 바로 시작 체크리스트

1. **Phase 2 편집기 UI 본격 구현**
   - [ ] Agent spec 조회/수정 폼 연결
   - [ ] 버전 목록 조회/복원 UI 연결
   - [ ] 테스트 실행(채팅 프리뷰) 버튼/결과 패널 구현
2. **RAG 고도화 준비**
   - [ ] 현재 토큰 오버랩 방식 확인
   - [ ] pgvector 기반 검색 경로로 대체 설계
3. **OpenAI 호환 API 정합성 보강**
   - [ ] 스트리밍 event shape edge case 테스트 추가
   - [ ] usage/error 포맷 케이스 보강

## 내일 시작 권장 명령어

```bash
# 1) 저장소 이동
cd /workspace/deep-agents

# 2) 브랜치/작업상태 확인
git status --short --branch

# 3) 테스트 선실행 (회귀 확인)
pytest -q

# 4) 백엔드 로컬 실행
cd backend
uvicorn app.main:app --reload
```

## 리스크/메모

- Phase 2가 미완료이므로 제품 전체 완성도 상한이 낮게 유지됩니다.
- 백엔드 API는 스모크 테스트 기준으로 기본 동작이 확인되어, 내일은 FE 연결 우선 전략이 효율적입니다.
