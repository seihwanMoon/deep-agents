# deep-agents

원격 문서(`origin/main:deep_agent_vibe_coding_plan_v2.md`)의 Phase 계획을 기준으로 개발을 진행했습니다.

## Phase 진행 현황 (현재)

- Phase 0: ✅ Docker Compose / FastAPI / SQLAlchemy / Alembic / JWT auth 기본 구현
- Phase 1: ✅ Agent/Folder CRUD, 버전 스냅샷, import/export API 구현
- Phase 2: 🚧 `/app/agent/{id}/edit` 경량 편집기 추가 (JWT 입력 기반으로 Agent/Settings/Versions 조회·수정 가능, 오프너 편집/버전 diff·restore 포함, editor-state 단일 조회 지원)
- Phase 3: ✅ LangGraph 기반 SSE 채팅 엔드포인트 골격 구현
- Phase 4: ✅ Tools/Models/Secrets API 구현
- Phase 5: ✅ Fix Agent 엔드포인트 + 기본 미들웨어 + 파일 업로드/RAG 컨텍스트 주입(질의 토큰 기반 우선순위)
- Phase 6: ✅ Schedules API + OpenAI 호환 `/v1/chat/completions` + 코드 스니펫/MCP/Webhook 엔드포인트

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
- `GET /app/agent/{id}/edit`로 Agent 기본정보/설정/최근 버전 조회, diff 확인, restore 실행까지 가능한 경량 편집기를 제공합니다(`editor-state` 단일 조회 사용).
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
  - `GET /api/v1/agents/{id}/versions/{version_no}`
  - `GET /api/v1/agents/{id}/versions/{version_no}/diff`
  - `POST /api/v1/agents/{id}/versions/{version_no}/restore`
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


## 구현 현황 리포트

- 현재 전체/Phase 진행률 평가는 `IMPLEMENTATION_STATUS.md`를 참고하세요.
