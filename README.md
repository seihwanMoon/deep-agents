# deep-agents

원격 문서(`origin/main:deep_agent_vibe_coding_plan_v2.md`)의 Phase 계획을 기준으로 개발을 진행했습니다.

## Phase 진행 현황 (현재)

- Phase 0: ✅ Docker Compose / FastAPI / SQLAlchemy / Alembic / JWT auth 기본 구현
- Phase 1: ✅ Agent/Folder CRUD, 버전 스냅샷, import/export API 구현
- Phase 2: ✅ `/app/agent/{id}/edit` 경량 편집기 추가 (JWT 입력 기반으로 Agent/Settings/Versions 조회·수정 가능, 오프너 편집/버전 diff·restore/수동 snapshot/버전 compare/Webhook 토큰 재발급/버전 삭제/오래된 버전 정리/버전 통계/버전 상세 보기/타임라인/변경 필드 통계/필드 변경 검색/버전 리포트/리포트 요약/리포트 Markdown/리포트 CSV/상위 변경 필드/리포트 JSONL/리포트 YAML/리포트 XML 포함)
- Phase 3: 🚧 LangGraph 기반 SSE 채팅 엔드포인트 골격 구현 (고도화 진행 필요)
- Phase 4: 🚧 Tools/Models/Secrets API 구현 (백엔드 중심, UI 미구현)
- Phase 5: 🚧 Fix Agent 엔드포인트 + 기본 미들웨어 + 파일 업로드/RAG 컨텍스트 주입(질의 토큰 기반 우선순위, 고급 로직 미완)
- Phase 6: 🚧 Schedules API + OpenAI 호환 `/v1/chat/completions` + 코드 스니펫/MCP/Webhook 엔드포인트 (기본 구현)

## 백엔드 실행

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 테스트 실행

```bash
# 저장소 루트에서
pytest -q
```

## UI 목업 (첨부 시안 반영)

- `GET /`로 사이드바 + 주요 화면(새 에이전트, 편집기, 템플릿, 유틸리티, 작업, 에셋, 설정) 목업 UI를 제공합니다.
- `GET /app/agent/{id}/edit`로 Agent 기본정보/설정/최근 버전 조회, diff 확인, restore 실행, 수동 snapshot 생성, 버전 compare, Webhook 토큰 재발급, 버전 삭제, 오래된 버전 정리, 버전 통계 조회, 버전 상세 보기, 타임라인 조회, 변경 필드 통계 조회, 필드 변경 검색, 버전 리포트 조회, 리포트 요약 조회, 리포트 Markdown/CSV/JSONL/YAML/XML 생성, 상위 변경 필드 조회까지 가능한 경량 편집기를 제공합니다.
  - 리포트 조회 limit 입력값(1~100)과 상위 필드 top_n 입력값(1~50)으로 리포트/타임라인/변경 필드 통계/필드 검색 및 top-fields 조회 범위를 제어할 수 있습니다.
  - 조회 조건 초기화 버튼으로 limit/top_n/keep_latest/검색/비교 입력값을 기본 상태로 즉시 되돌릴 수 있습니다.
  - 조회 조건(limit/top_n/keep_latest/검색/비교)은 로컬 스토리지에 저장되어 다음 접속 시 복원됩니다.
  - 결과 복사/결과 초기화/결과 다운로드 버튼으로 리포트/비교 결과를 재사용하기 쉽게 했습니다.
    - 다운로드 형식은 `txt/json` 선택 가능하며, 설정은 조회 조건과 함께 저장됩니다.
    - 결과 내 검색(하이라이트) 적용/해제 기능으로 긴 출력 확인을 보조합니다.
    - 대용량 출력은 기본적으로 preview로 렌더하고 `전체 출력 보기`로 확장해 UI 멈춤을 줄였습니다.
    - 하이라이트 렌더링은 DOM 노드 기반으로 처리하여 출력 텍스트 HTML이 그대로 실행되지 않도록 했습니다.
    - 기본 안내 문구 상태에서는 복사/다운로드를 막아 의미 없는 빈 결과 저장을 방지합니다.
  - 리포트 액션 버튼에서 XML 조회 상태/실패 메시지를 `versionStatus` 영역으로 일관 표시합니다.
- 정적 파일: `backend/app/static/index.html`, `backend/app/static/agent-editor.html`, `backend/app/static/ui.css`

## 핵심 엔드포인트

- Auth
  - `POST /api/v1/auth/login`
  - `GET /api/v1/auth/me`
- Folders
  - `GET/POST /api/v1/folders`
  - `GET/PUT/DELETE /api/v1/folders/{folder_id}`
- Agents
  - `GET/POST/PUT/DELETE /api/v1/agents`
  - `GET /api/v1/agents/{id}`
  - `GET /api/v1/agents/{id}/editor-state` (편집기 초기 로드용 단일 응답)
  - `GET/PUT /api/v1/agents/{id}/settings`
  - `POST /api/v1/agents/{id}/fix`
  - `GET/PUT /api/v1/agents/{id}/openers`
  - `POST /api/v1/agents/{id}/files`
  - `GET /api/v1/agents/{id}/snippet`
  - `GET /api/v1/agents/{id}/snippet/languages`
  - `GET /api/v1/agents/{id}/mcp`
  - `POST /api/v1/agents/{id}/webhook-token/rotate`
  - `POST /api/v1/agents/{id}/webhook`
  - `GET /api/v1/agents/{id}/versions` (`limit`, `offset`, `include_snapshot` 지원)
  - `POST /api/v1/agents/{id}/versions/snapshot`
  - `GET /api/v1/agents/{id}/versions/compare` (`from_version`, `to_version`)
  - `GET /api/v1/agents/{id}/versions/{version_no}`
  - `GET /api/v1/agents/{id}/versions/{version_no}/diff`
  - `POST /api/v1/agents/{id}/versions/{version_no}/restore`
  - `DELETE /api/v1/agents/{id}/versions/{version_no}`
  - `DELETE /api/v1/agents/{id}/versions` (`keep_latest`)
  - `GET /api/v1/agents/{id}/versions/meta/stats`
  - `GET /api/v1/agents/{id}/versions/meta/timeline`
  - `GET /api/v1/agents/{id}/versions/meta/fields` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/search` (`field`, `limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report/summary` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report/markdown` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report/csv` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report/top-fields` (`limit`, `top_n`)
  - `GET /api/v1/agents/{id}/versions/meta/report/jsonl` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report/yaml` (`limit`)
  - `GET /api/v1/agents/{id}/versions/meta/report/xml` (`limit`)
    - XML 응답은 `<latest>`, `<timeline>`, `<field_stats>`를 포함한 구조화 포맷으로 제공
  - `POST /api/v1/agents/import` (openers 포함 import 지원)
- Chat
  - `POST /api/v1/agents/{id}/chat` (SSE)
  - `GET /api/v1/agents/{id}/conversations`
  - `GET /api/v1/agents/{id}/conversations/{conversation_id}`
  - `GET /api/v1/agents/{id}/conversations/{conversation_id}/messages`
  - `DELETE /api/v1/agents/{id}/conversations/{conversation_id}/messages`
  - `DELETE /api/v1/agents/{id}/conversations/{conversation_id}/messages/{message_id}`
  - `PUT /api/v1/agents/{id}/conversations/{conversation_id}`
  - `DELETE /api/v1/agents/{id}/conversations/{conversation_id}`
  - `POST /v1/chat/completions` (OpenAI 호환)
  - `GET /v1/models` (OpenAI 호환 모델 목록)
- Phase 4/6 supporting APIs
  - `GET/POST/PUT/DELETE /api/v1/tools`
  - `GET /api/v1/tools/{tool_id}/discover`
  - `POST /api/v1/tools/{tool_id}/invoke/{tool_name}`
  - `GET /api/v1/models/providers`
  - `GET /api/v1/middlewares` (미들웨어 레지스트리/설정 스키마 목록, `provider/category/q` 필터 지원)
  - `GET /api/v1/middlewares/{middleware_key}`
  - `GET/POST/PUT/DELETE /api/v1/secrets` (저장 시 암호화, 조회 시 마스킹)
  - `GET/POST /api/v1/agents/{id}/schedules`
  - `PUT/DELETE /api/v1/agents/{id}/schedules/{schedule_id}` (자동 beat 동기화)
  - `POST /api/v1/agents/{id}/schedules/sync` (수동 Celery beat 동기화)



## 현재까지 진척사항 요약 (업데이트)

- 이번 반영으로 **Phase 2(에디터/버전 관리) 트랙은 100% 완료**로 정리했습니다.
- Phase 2는 편집기 UX + API + 스모크/CI 회귀 반영으로 **100% 완료**로 조정했습니다.
- 최근 안정화된 편집기 개선 포인트:
  - XML 리포트 액션/상태 표시 일관화
  - 리포트/메타 조회 범위 제어(limit/top_n)
  - 조회 조건 초기화 버튼
  - 조회 조건 로컬 스토리지 저장/복원 (keep_latest 포함)
  - 결과 다운로드 + 기본 안내 문구 보호(copy/download guard)
  - 다운로드 형식 선택(txt/json) + 설정 저장
  - 결과 내 검색 하이라이트/해제
  - 대용량 출력 preview/전체 보기 분리

## 구현 현황 리포트

- 현재 전체/Phase 진행률 평가는 `IMPLEMENTATION_STATUS.md`를 참고하세요.
- 다음 작업 재개 체크리스트는 `HANDOFF.md`를 참고하세요.
- 스모크 테스트에 CSV 특수문자(쉼표/개행/인용부호) 직렬화 검증과 top-fields 쿼리 경계값 검증을 추가했습니다.
- 스모크 테스트에 `meta/search`, `meta/fields` limit 경계값 검증도 추가했습니다.
- Playwright 기반 에디터 UI 스모크(`backend/tests/test_ui_playwright_smoke.py`)를 추가해 버튼 클릭 시 상태 패널 변경을 E2E로 검증합니다.
