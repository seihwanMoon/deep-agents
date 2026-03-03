# Handoff (2026-03-03)

## 현재 상태 요약

- branch: `work`
- 최신 진행률(문서 기준):
  - 전체(전체 Phase 기준): **약 78%**
  - Phase 2: **100%**
- 최근 연속 반영된 안정화 항목:
  - `fix` 입력 JSON object 강제 + 예외 시 rollback 보강
  - RAG 소스 선택 점수화(phrase match/substring/token overlap)
  - OpenAI-compat `response_format`(`text`/`json_object`) 지원
  - webhook callback 상태 검증/중복 충돌 메타데이터/created_after 필터/recent stats 확장

## 최근 커밋(내일 이어받기 기준)

```bash
git log --oneline -n 6
# 154ae02 Enhance webhook callback observability and filtering
# 6d9c790 Add response_format support to OpenAI-compatible chat endpoint
# dbfa96c Expand OpenAI-compatible message format handling
# 35db820 Improve RAG source ranking with phrase-aware scoring
# aae41fc Harden fix endpoint to structured JSON-only operations
# 8a1406d Add Agent Editor UI + Versioning/Webhook APIs, schedule sync improvements, tests & CI smoke
```

## 오늘 기준 검증 완료 항목

아래 테스트 셋 통과 확인:

```bash
pytest -q backend/tests/test_api_smoke.py -k "webhook_callback or webhook_callbacks_listing_filters or webhook_callbacks_listing_offset_pagination or webhook_callbacks_filter_by_created_after"
pytest -q backend/tests/test_api_smoke.py -k "openai_compat_response_format_json_object_non_stream or openai_compat_response_format_json_object_streaming or openai_compat_rejects_unsupported_response_format or openai_stream_chunk_contract_usage_toggle"
```

## 남은 핵심 개발 항목 (우선순위)

1. **RAG 실검색 전환**
   - [ ] pgvector 기반 임베딩 저장/유사도 검색 경로 활성화
   - [ ] 현재 토큰 점수화 로직과 실검색 로직 간 fallback 정책 정리
   - [ ] 회귀 테스트(검색 품질 + no-hit fallback) 추가

2. **운영 안정성/E2E 확장**
   - [ ] Celery beat 동적 반영(런타임 sync) 검증 보강
   - [ ] webhook async callback 재시도 시나리오(E2E) 추가
   - [ ] OpenAI-compat 스트리밍 포맷 E2E 확장(응답 포맷 변형 케이스)

3. **문서/가이드 최신화**
   - [ ] README의 OpenAI-compat 입력/response_format 예시 추가
   - [ ] IMPLEMENTATION_STATUS 재평가 트리거 상태 업데이트

## 내일 시작 권장 명령어

```bash
# 1) 저장소 진입
cd /workspace/deep-agents

# 2) 상태 확인
git status --short --branch
git log --oneline -n 12

# 3) 빠른 회귀 확인
pytest -q backend/tests/test_api_smoke.py -k "webhook_callback"
pytest -q backend/tests/test_api_smoke.py -k "openai_compat_response_format_json_object_non_stream or openai_compat_response_format_json_object_streaming"

# 4) 서버 실행
cd backend
uvicorn app.main:app --reload
```

## 참고

- 제품/엔드포인트 개요: `README.md`
- 단계별 진행률/근거: `IMPLEMENTATION_STATUS.md`
