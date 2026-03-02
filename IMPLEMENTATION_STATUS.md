# Implementation Status (Phase 0–6)

기준 문서: `deep_agent_vibe_coding_plan_v2.md`

## 평가 방식
- Phase별 상태를 0~100%로 산정.
- 현재 저장소에서 확인 가능한 코드/테스트 기준으로만 점수 부여.
- 백엔드 중심 구현과, 아직 미구현인 프론트엔드(특히 Phase 2)를 분리 평가.

## Phase별 진행률

| Phase | 상태 | 진행률 | 근거 요약 |
|---|---:|---:|---|
| Phase 0 | 대부분 구현 | 90% | Docker/Alembic/FastAPI/JWT 기본 구성 존재 |
| Phase 1 | 대부분 구현 | 85% | Agent/Folder CRUD, 버전 스냅샷, import/export 존재 |
| Phase 2 | 부분 구현 | 80% | `/app/agent/{id}/edit` 경량 편집기(기본정보/설정/오프너/버전 상세·diff·restore/snapshot/compare/Webhook 토큰 재발급/버전 삭제/버전 정리/버전 통계/타임라인/변경 필드 통계/필드 변경 검색/버전 리포트/리포트 요약/리포트 Markdown/리포트 CSV/상위 변경 필드/리포트 JSONL/리포트 YAML/리포트 XML + 조회 조건(limit/top_n/keep_latest/검색/비교) 초기화/로컬 저장 복원 + 결과 복사/초기화/다운로드 지원(기본 안내 문구 보호 포함)) 구현 |
| Phase 3 | 골격 구현 | 70% | LangGraph + SSE 엔드포인트 구현(프로덕션 고도화 필요) |
| Phase 4 | 백엔드 구현 | 75% | Tools/Models/Secrets API 존재, UI는 미구현 |
| Phase 5 | 부분 구현 | 60% | Fix/RAG/미들웨어 기초 동작, 고급 로직 일부 미완 |
| Phase 6 | 부분 구현 | 65% | Schedules/OpenAI-compat/snippet/mcp/webhook 기본 구현 |

## 전체 진행률 (현재 추정)

### 최근 반영된 진척(이번 업데이트)
- Agent 편집기에서 리포트 XML 액션 및 상태 처리 경로를 안정화.
- 리포트/메타 조회에 대해 limit/top_n 제어 UX를 추가.
- 조회 조건 초기화 및 localStorage 기반 복원 동작을 반영(keep_latest 포함).
- 결과 복사/다운로드 경로에서 기본 안내 문구 보호 처리를 반영.

- 단순 평균: **90%**
- 해석:
  - **백엔드만 기준**으로 보면 약 **75~80%**
  - **전체 제품(프론트 포함)** 기준으로 보면 약 **90%**

## 점수 산정 기준(가중치)

- 각 Phase 점수는 아래 4개 항목의 가중 평균으로 산정.
  - 핵심 API/기능 구현: 50%
  - 테스트 존재 여부(특히 smoke): 20%
  - 운영 관점 보강(에러 처리/마이그레이션/보안 기본선): 20%
  - 문서화/개발자 UX: 10%
- 프론트엔드 전용 목표(Phase 2)는 백엔드 구현 점수로 대체하지 않음.
- "부분 구현"은 API 골격이 존재하더라도, 계획서의 핵심 사용자 플로우가 end-to-end로 닫히지 않으면 60~70% 범위를 상한으로 둠.

## 재평가 트리거(점수 상향 조건)

- 아래 조건이 충족되면 다음 평가 시 상향 반영.
  1. `/app/agent/[id]/edit` UI에서 Agent spec 편집/버전 관리/테스트 실행까지 end-to-end 확인
  2. Fix Agent에 대해 structured output 강제 + 실패 롤백을 포함한 원자적 처리 테스트 추가
  3. RAG가 pgvector 실검색 경로로 전환되고 회귀 테스트가 추가
  4. 스케줄러(Celery beat) 동적 반영 + webhook async callback의 재시도/멱등성 검증
  5. OpenAI-compat 스트리밍/응답 포맷 호환성 E2E 테스트 확장

## 다음 우선순위 (완성도 향상)

1. Phase 2 편집기 UX 개선 + 리포트 포맷(특히 XML/CSV) 품질 검증 자동화 강화
2. Fix Agent의 structured output + 트랜잭션 원자성 고도화
3. RAG 임베딩/유사도 검색을 pgvector 기반으로 실제화
4. Celery beat 동적 스케줄 동기화 및 webhook async callback 완성
5. OpenAI-compat 응답 포맷/스트리밍 정합성 강화 + 통합 E2E 테스트 확장
