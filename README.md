# deep-agents

원격 문서(`origin/main:deep_agent_vibe_coding_plan_v2.md`)의 Phase 계획을 기준으로 개발을 진행했습니다.

## Phase 진행 현황 (현재)

- Phase 0: ✅ Docker Compose / FastAPI / SQLAlchemy / Alembic / JWT auth 기본 구현
- Phase 1: ✅ Agent/Folder CRUD, 버전 스냅샷, import/export API 구현
- Phase 2: ⏳ 프론트엔드 편집기 미구현 (백엔드 API 기반 준비)
- Phase 3: ✅ LangGraph 기반 SSE 채팅 엔드포인트 골격 구현
- Phase 4: ✅ Tools/Models/Secrets API 구현
- Phase 5: ✅ Fix Agent 엔드포인트 + 기본 미들웨어 + 파일 업로드/RAG 컨텍스트 주입
- Phase 6: ✅ Schedules API + OpenAI 호환 `/v1/chat/completions` + 코드 스니펫/MCP/Webhook 엔드포인트

## 백엔드 실행

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 핵심 엔드포인트

- Auth
  - `POST /api/v1/auth/login`
  - `GET /api/v1/auth/me`
- Agents
  - `GET/POST/PUT/DELETE /api/v1/agents`
  - `POST /api/v1/agents/{id}/fix`
  - `POST /api/v1/agents/{id}/files`
  - `GET /api/v1/agents/{id}/snippet`
  - `GET /api/v1/agents/{id}/mcp`
  - `POST /api/v1/agents/{id}/webhook`
  - `GET /api/v1/agents/{id}/versions`
- Chat
  - `POST /api/v1/agents/{id}/chat` (SSE)
  - `POST /v1/chat/completions` (OpenAI 호환)
- Phase 4/6 supporting APIs
  - `GET/POST/PUT/DELETE /api/v1/tools`
  - `GET /api/v1/models/providers`
  - `GET/POST/PUT/DELETE /api/v1/secrets`
  - `GET/POST /api/v1/agents/{id}/schedules`
  - `PUT/DELETE /api/v1/agents/{id}/schedules/{schedule_id}`


## 구현 현황 리포트

- 현재 전체/Phase 진행률 평가는 `IMPLEMENTATION_STATUS.md`를 참고하세요.
