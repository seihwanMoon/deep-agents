# Deep Agent Builder — 클론 코딩 상세 개발 계획서 v2.0

> **내부 전용 · AI 바이브 코딩 최적화 · 전체 사이트 탐색 반영**
> 작성일: 2026년 3월 | 기반: deepagent-builder.ai 전체 탐색

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [전체 기능 인벤토리](#2-전체-기능-인벤토리-사이트-탐색-결과)
3. [도구 시스템 (43종)](#3-도구-시스템-43종)
4. [모델 레지스트리 (7개 공급사, 40+ 모델)](#4-모델-레지스트리-7개-공급사-40-모델)
5. [미들웨어 시스템 (18종)](#5-미들웨어-시스템-18종)
6. [스킬 시스템](#6-스킬-시스템)
7. [프로젝트 디렉토리 구조](#7-프로젝트-디렉토리-구조)
8. [전체 데이터베이스 스키마](#8-전체-데이터베이스-스키마)
9. [API 엔드포인트 전체 목록](#9-api-엔드포인트-전체-목록)
10. [단계별 구현 계획](#10-단계별-구현-계획)
11. [핵심 구현 패턴 레퍼런스](#11-핵심-구현-패턴-레퍼런스)
12. [환경변수 & 배포 가이드](#12-환경변수--배포-가이드)

---

## 1. 프로젝트 개요

### 1.1 목적 및 범위

deepagent-builder.ai(Braincrew Inc.)의 멀티 에이전트 빌더 플랫폼을 **내부 전용**으로 클론 코딩한다.
AI 바이브 코딩(Cursor, Claude Code 등)으로 개발하며, 팀 내 자동화 에이전트를 빠르게 구축·운영하는 것이 목표다.

### 1.2 내부 전용 간소화 항목

> ✅ 아래 항목은 내부 전용이므로 **처음부터 제외**하고 구현한다.

- **멀티 테넌시** (조직/팀 분리) — 단일 조직으로 고정
- **결제 시스템** (Stripe 등) — 완전 제거
- **OAuth 소셜 로그인** (Google/GitHub) — 제거, 단순 JWT 이메일+비밀번호
- **이메일 인증** (이메일 발송) — 관리자가 직접 계정 생성
- **Rate Limiting** (API 요청 제한) — 제거 또는 단순화
- **외부 Webhook 보안 검증** — 내부 네트워크 신뢰
- **S3/외부 파일 스토리지** — 로컬 파일 시스템
- **Audit Log** (상세 사용 감사) — 최소화
- **사용량 대시보드 / 과금 대시보드** — 제거
- **공개 에이전트 마켓플레이스** — 커뮤니티 탭 제거 가능
- **엔터프라이즈 SSO** — 제거
- **사용자 초대 이메일** — 직접 계정 생성으로 대체

### 1.3 기술 스택

| 레이어 | 기술 | 비고 |
|--------|------|------|
| Frontend | Next.js 14 (App Router) | TypeScript, Tailwind CSS |
| Backend | FastAPI (Python 3.11+) | Pydantic v2, async/await |
| Agent 오케스트레이션 | LangGraph | StateGraph, ToolNode, astream_events |
| Database | PostgreSQL 16 | pgvector 확장 (RAG용) |
| Cache / Queue | Redis | Celery 브로커 + 결과 백엔드 |
| Background Tasks | Celery | 스케줄링, 비동기 에이전트 실행 |
| Auth | JWT (내부 간소화) | python-jose, bcrypt |
| ORM | SQLAlchemy 2.0 | Alembic 마이그레이션 |
| File Storage | Local filesystem | 내부 전용 — S3 불필요 |
| Streaming | Server-Sent Events (SSE) | FastAPI StreamingResponse |
| MCP | Model Context Protocol | Claude Desktop / Cursor 연동 |

---

## 2. 전체 기능 인벤토리 (사이트 탐색 결과)

### 2.1 사이드바 네비게이션 구조

| 항목 | 설명 |
|------|------|
| 새 에이전트 | 새 에이전트 생성 버튼 (항상 상단) |
| 에이전트 템플릿 | 미리 만들어진 템플릿 목록 |
| 유틸리티 | 유틸리티 에이전트 목록 |
| 에이전트 목록 | 폴더별 에이전트 트리 (미분류 = 기본 폴더) |
| 즐겨찾기 | 즐겨찾기된 에이전트 빠른 접근 |
| 커뮤니티 | 커뮤니티 공유 에이전트 (내부 전용 시 제거 가능) |
| 사용자 프로필 | 하단 고정, 사용자명/이메일 표시 |
| 에이전트 가져오기 | 외부 에이전트 JSON 임포트 버튼 |

### 2.2 에이전트 편집기 (7탭 구조)

에이전트 편집기는 **좌측 설정 패널 + 우측 7탭 패널**로 구성된다.

#### 좌측 패널 — 에이전트 설정

| 항목 | 설명 |
|------|------|
| 에이전트 이름 | 텍스트 입력, 상단 표시 |
| 설명 | 짧은 설명 텍스트 |
| 시스템 프롬프트 | 폼/비주얼 뷰 전환 + 에디터 확장 (전체화면) |
| 서브 에이전트 | 다른 에이전트를 도구로 추가 (멀티에이전트) |
| 모델 | 7개 공급사 중 선택, `provider:model-name` 형식 |
| 도구 | 43개 도구 추가 (built-in, custom, MCP, HTTP) |
| 미들웨어 | 18종 미들웨어 파이프라인 구성 |

#### 우측 탭 패널 (7탭)

| 탭 | 기능 | 상세 |
|----|------|------|
| Fix 에이전트 | 자연어로 에이전트 수정 | 시스템 프롬프트+도구+오프너 원자적 변경 |
| 테스트 | 실시간 채팅 테스트 | SSE 스트리밍, 대화 히스토리 |
| 오프너 | 대화 시작 버튼 | 최대 12개, 페이지네이션 |
| 파일 | RAG 파일 첨부 | pgvector 기반 문서 검색 |
| 스킬 | 스킬 파일 관리 | 업로드 또는 AI 어시스턴트 생성 |
| 스케줄 | Cron 스케줄링 | 자동 실행, Celery 연동 |
| 설정 | 에이전트 고급 설정 | Recursion Limit (1-1000, 기본 25), Webhook 토큰 |

### 2.3 시스템 프롬프트 에디터

| 기능 | 설명 |
|------|------|
| 폼 뷰 | 구조화된 섹션별 입력 (역할, 지침, 제약 등) |
| 비주얼 뷰 | 마크다운 렌더링 미리보기 |
| 에디터 확장 | 전체화면 에디터 모달 |
| 코드 스니펫 | 에이전트 API 호출 코드 생성 버튼 |
| 버전 관리 | v0 → v1 → ... 이력 저장 및 롤백 |

### 2.4 코드 스니펫 API

모든 에이전트는 **OpenAI 호환 API**로 노출된다.

```python
# Python SDK (OpenAI 호환)
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="dbuilder_xxx")
response = client.chat.completions.create(
    model="agent-{agent_id}",
    messages=[{"role": "user", "content": "질문"}],
    stream=True
)
```

```bash
# cURL
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer dbuilder_xxx" \
  -H "Content-Type: application/json" \
  -d '{"model": "agent-{id}", "messages": [...]}'
```

> LangChain, TypeScript SDK도 지원

### 2.5 Webhook 설정

| 항목 | 설명 |
|------|------|
| 토큰 형식 | `dbuilder_xxxxxxxxxxxxxxxxxx` |
| 인증 헤더 | `Authorization: Bearer dbuilder_xxx` |
| n8n 연동 | 외부 워크플로우에서 에이전트 호출 |
| Dify 연동 | Dify 플랫폼 연동 |
| MCP 서버 | 에이전트별 MCP 서버 활성화 (Claude Desktop, Cursor 지원) |

---

## 3. 도구 시스템 (43종)

### 3.1 도구 유형 분류

| 유형 | 설명 | 예시 |
|------|------|------|
| built-in | 내장 도구 (5종) | arxiv, duckduckgo, tavily, wikipedia, sequential_thinking |
| custom | 사용자 정의 Python 함수 | 팀 내부 API, 커스텀 로직 |
| mcp(원격) | MCP Remote 서버 연결 | stdio/SSE 방식 외부 MCP |
| mcp(로컬) | MCP Local 프로세스 | 로컬 npx/uvx 명령 |
| HTTP | REST API 직접 호출 | OpenAPI 스펙 또는 수동 설정 |

### 3.2 Built-in 도구 (5종)

| 도구 | 설명 |
|------|------|
| `arxiv` | 학술 논문 검색 (arXiv API) |
| `duckduckgo` | 웹 검색 (DuckDuckGo) |
| `tavily` | AI 특화 웹 검색 (Tavily API — secrets 필요) |
| `wikipedia` | 위키백과 검색 |
| `sequential_thinking` | 단계적 추론 도구 (Chain-of-Thought) |

### 3.3 Secrets 관리 (API 키 저장소)

도구에 필요한 API 키를 중앙 집중식으로 관리한다. MCP 도구 42개에 대한 키를 사전 등록할 수 있다.

| 항목 | 설명 |
|------|------|
| 범위 | User 스코프 또는 Workspace 스코프 |
| 저장 형식 | Key-Value (예: `TAVILY_API_KEY = sk-xxx`) |
| 용도 | MCP 도구, HTTP 도구, Custom 도구의 API 키 참조 |
| 보안 | 암호화 저장, 에이전트 실행 시 환경변수로 주입 |
| 등록 가능 키 | 42종 (MCP 도구별 1개) |

---

## 4. 모델 레지스트리 (7개 공급사, 40+ 모델)

### 4.1 모델 명명 규칙

```
형식: provider:model-name

예시:
  anthropic:claude-opus-4-5-20251101
  anthropic:claude-sonnet-4-6
  openai:gpt-4o
  openai:gpt-4o-mini
  azure:gpt-4o
  azure:gpt-5-mini
  google:gemini-2.0-flash
  google:gemini-2.5-pro
  bedrock:us.amazon.nova-pro-v1:0
  openrouter:deepseek/deepseek-chat
  bizrouter:K-EXAONE-3.5
  bizrouter:Solar-pro
```

### 4.2 공급사별 모델 목록

| 공급사 | 주요 모델 | 비고 |
|--------|-----------|------|
| Anthropic | claude-opus-4-5, claude-sonnet-4-6, claude-haiku-4-5 | 기본 공급사 권장 |
| OpenAI | gpt-4o, gpt-4o-mini, o1, o3-mini, gpt-4.1 | OpenAI API 키 필요 |
| Google | gemini-2.0-flash, gemini-2.5-pro, gemini-1.5-pro | Google AI API 키 필요 |
| Azure | gpt-4o, gpt-5-mini (Azure 배포) | Azure OpenAI 엔드포인트 |
| Bedrock | amazon.nova-pro, amazon.nova-lite, claude (bedrock) | AWS 자격증명 필요 |
| OpenRouter | deepseek-chat, llama-3.3-70b, qwen 등 | OpenRouter API 키 필요 |
| BizRouter | K-EXAONE-3.5, Solar-pro | 국내 LLM (한국어 특화) |
| Custom | 사용자 정의 엔드포인트 | base_url + api_key 직접 입력 |

### 4.3 모델 레지스트리 DB 스키마

```sql
-- model_providers 테이블
CREATE TABLE model_providers (
  id         SERIAL PRIMARY KEY,
  name       VARCHAR(50) UNIQUE NOT NULL,  -- anthropic, openai, ...
  display    VARCHAR(100),
  base_url   TEXT,                         -- Custom 공급사용
  enabled    BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- models 테이블
CREATE TABLE models (
  id          SERIAL PRIMARY KEY,
  provider_id INTEGER REFERENCES model_providers(id),
  model_id    VARCHAR(200) NOT NULL,        -- e.g. claude-sonnet-4-6
  display     VARCHAR(200),
  context_len INTEGER DEFAULT 200000,
  enabled     BOOLEAN DEFAULT true,
  UNIQUE(provider_id, model_id)
);
```

---

## 5. 미들웨어 시스템 (18종)

미들웨어는 에이전트 실행 파이프라인에 끼어들어 동작을 변경하는 컴포넌트다.
LangGraph의 StateGraph 실행 전/후에 적용된다.

### 5.1 Built-in 미들웨어 (12종)

| 미들웨어 | 동작 | 주요 파라미터 |
|----------|------|--------------|
| `ContextEditingMiddleware` | 컨텍스트 동적 편집 | edit_prompt, context_key |
| `HumanInTheLoopMiddleware` | 사람 승인 대기 | approval_message, timeout_sec |
| `LLMToolEmulator` | 도구 없이 LLM으로 도구 에뮬레이션 | emulate_tools: list |
| `LLMToolSelectorMiddleware` | LLM이 도구 선택 결정 | selection_model |
| `ModelCallLimitMiddleware` | 모델 호출 횟수 제한 | max_calls: int |
| `ModelFallbackMiddleware` | 모델 실패 시 대체 모델 | fallback_models: list |
| `ModelRetryMiddleware` | 모델 오류 시 재시도 | max_retries, backoff_sec |
| `PIIMiddleware` | PII 데이터 마스킹 | pii_types: list, mask_char |
| `SummarizationMiddleware` | 긴 컨텍스트 자동 요약 | threshold_tokens, summary_model |
| `TodoListMiddleware` | Todo 리스트 자동 관리 | auto_update: bool |
| `ToolCallLimitMiddleware` | 도구 호출 횟수 제한 | max_tool_calls: int |
| `ToolRetryMiddleware` | 도구 실패 시 재시도 | max_retries, retry_delay |

### 5.2 Anthropic Provider 미들웨어 (5종)

| 미들웨어 | 동작 | 비고 |
|----------|------|------|
| `BashToolMiddleware` | Bash 명령 실행 지원 | Claude computer use 연동 |
| `FileSearchMiddleware` | 파일 내용 검색 | RAG + 직접 파일 검색 |
| `MemoryMiddleware` | 대화 간 메모리 지속 | Vector store 기반 장기 기억 |
| `PromptCachingMiddleware` | 프롬프트 캐싱 (Anthropic) | Beta 기능, 토큰 절약 |
| `TextEditorMiddleware` | 텍스트 파일 편집 도구 | str_replace_editor 패턴 |

### 5.3 OpenAI Provider 미들웨어 (1종)

| 미들웨어 | 동작 | 비고 |
|----------|------|------|
| `ModerationMiddleware` | 콘텐츠 안전성 검사 | OpenAI Moderation API 호출 |

### 5.4 미들웨어 파이프라인 구현

```python
# middleware/base.py
from abc import ABC, abstractmethod
from typing import Any

class BaseMiddleware(ABC):
    name: str
    description: str
    schema: dict  # JSON Schema for config parameters

    @abstractmethod
    async def before_invoke(self, state: dict, config: dict) -> dict:
        """에이전트 실행 전 호출"""
        ...

    @abstractmethod
    async def after_invoke(self, state: dict, config: dict, result: Any) -> Any:
        """에이전트 실행 후 호출"""
        ...

# agents/executor.py
class AgentExecutor:
    def __init__(self, agent, middlewares: list[BaseMiddleware]):
        self.graph = agent.build_graph()  # LangGraph StateGraph
        self.middlewares = middlewares

    async def astream(self, messages, config):
        state = {"messages": messages}
        for mw in self.middlewares:
            state = await mw.before_invoke(state, config)
        async for chunk in self.graph.astream_events(state, config):
            yield chunk
```

---

## 6. 스킬 시스템

스킬은 도구(Tool)와 다른 개념이다.
에이전트에게 특정 능력을 부여하는 **파일 기반 컴포넌트**로, 업로드하거나 AI 어시스턴트를 통해 생성한다.

### 6.1 스킬 특성

| 항목 | 설명 |
|------|------|
| 저장 방식 | 파일(텍스트/코드)로 에이전트에 첨부 |
| 생성 방법 | 직접 업로드 또는 AI 어시스턴트 채팅으로 생성 |
| 적용 범위 | 에이전트별 독립적으로 관리 |
| 파일 형식 | .md, .txt, .py 등 텍스트 파일 |
| 용도 | 프롬프트 인젝션, 코드 스니펫, 규칙 정의 |

### 6.2 스킬 생성 API

```json
// POST /api/v1/agents/{agent_id}/skills/generate
{
  "instruction": "Python pandas 데이터 분석 전문가로 행동하라",
  "context": "데이터 분석 에이전트에 사용할 스킬"
}

// 응답
{
  "skill_id": "uuid",
  "filename": "pandas_expert.md",
  "content": "# Pandas 분석 전문가\n\n...(생성된 내용)..."
}
```

### 6.3 DB 스키마

```sql
CREATE TABLE agent_skills (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  filename   VARCHAR(255) NOT NULL,
  content    TEXT NOT NULL,
  file_size  INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 7. 프로젝트 디렉토리 구조

### 7.1 백엔드 (FastAPI)

```
backend/
├── app/
│   ├── main.py                 # FastAPI 앱 엔트리포인트
│   ├── config.py               # 환경변수, 설정
│   ├── database.py             # SQLAlchemy 엔진/세션
│   ├── models/                 # SQLAlchemy ORM 모델
│   │   ├── user.py
│   │   ├── agent.py
│   │   ├── agent_version.py
│   │   ├── agent_folder.py
│   │   ├── tool.py
│   │   ├── middleware_config.py
│   │   ├── skill.py
│   │   ├── secret.py
│   │   ├── model_provider.py
│   │   ├── opener.py
│   │   ├── conversation.py
│   │   └── schedule.py
│   ├── schemas/                # Pydantic 스키마
│   ├── routers/                # API 라우터
│   │   ├── auth.py             # JWT 인증
│   │   ├── agents.py           # 에이전트 CRUD + 실행
│   │   ├── tools.py            # 도구 관리
│   │   ├── models.py           # 모델 레지스트리
│   │   ├── middlewares.py      # 미들웨어 설정
│   │   ├── skills.py           # 스킬 관리
│   │   ├── secrets.py          # Secrets 관리
│   │   ├── chat.py             # SSE 스트리밍 채팅
│   │   ├── snippets.py         # 코드 스니펫 API
│   │   └── schedule.py         # Celery 스케줄
│   ├── agents/                 # 에이전트 엔진
│   │   ├── builder.py          # LangGraph 그래프 빌더
│   │   ├── executor.py         # 미들웨어 파이프라인 실행기
│   │   ├── fix_agent.py        # Fix 에이전트 (자연어 수정)
│   │   └── rag.py              # pgvector RAG
│   ├── middleware/             # 18종 미들웨어 구현
│   │   ├── base.py
│   │   ├── builtin/            # 12종 built-in
│   │   ├── anthropic/          # 5종 Anthropic
│   │   └── openai/             # 1종 OpenAI
│   ├── tools/                  # 도구 실행기
│   │   ├── builtin.py          # arxiv, duckduckgo 등
│   │   ├── mcp_remote.py       # MCP Remote
│   │   ├── mcp_local.py        # MCP Local
│   │   └── http_tool.py        # HTTP REST 도구
│   ├── tasks/                  # Celery 태스크
│   │   ├── agent_run.py        # 에이전트 비동기 실행
│   │   └── scheduler.py        # 크론 스케줄
│   └── utils/
├── alembic/                    # DB 마이그레이션
├── requirements.txt
└── Dockerfile
```

### 7.2 프론트엔드 (Next.js 14)

```
frontend/
├── app/
│   ├── layout.tsx              # 루트 레이아웃
│   ├── page.tsx                # 랜딩 페이지
│   ├── login/page.tsx
│   └── app/
│       ├── layout.tsx          # 앱 레이아웃 (사이드바)
│       ├── page.tsx            # 에이전트 목록
│       └── agent/[id]/edit/page.tsx  # 에이전트 편집기
├── components/
│   ├── sidebar/                # 사이드바 컴포넌트
│   │   ├── Sidebar.tsx
│   │   ├── AgentTree.tsx       # 폴더 트리
│   │   └── FolderItem.tsx
│   ├── agent-editor/
│   │   ├── AgentEditor.tsx     # 메인 에디터
│   │   ├── LeftPanel.tsx       # 설정 패널
│   │   ├── SystemPromptEditor.tsx  # 폼/비주얼 뷰
│   │   ├── RightTabs.tsx       # 7탭 패널
│   │   └── tabs/               # 각 탭 컴포넌트
│   │       ├── FixAgentTab.tsx
│   │       ├── TestTab.tsx     # SSE 채팅
│   │       ├── OpenersTab.tsx
│   │       ├── FilesTab.tsx
│   │       ├── SkillsTab.tsx
│   │       ├── ScheduleTab.tsx
│   │       └── SettingsTab.tsx
│   ├── tools/                  # 도구 관리 UI
│   ├── models/                 # 모델 레지스트리 UI
│   ├── middlewares/            # 미들웨어 설정 UI
│   ├── secrets/                # Secrets 관리 UI
│   └── chat/                   # 채팅 UI
├── lib/
│   ├── api.ts                  # API 클라이언트
│   ├── auth.ts                 # JWT 처리
│   └── sse.ts                  # SSE 스트림 핸들러
└── types/                      # TypeScript 타입 정의
```

---

## 8. 전체 데이터베이스 스키마

```sql
-- 사용자
CREATE TABLE users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email      VARCHAR(255) UNIQUE NOT NULL,
  name       VARCHAR(100),
  hashed_pw  VARCHAR(255) NOT NULL,
  is_admin   BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 에이전트 폴더
CREATE TABLE agent_folders (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id),
  name       VARCHAR(100) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 에이전트
CREATE TABLE agents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id),
  folder_id       UUID REFERENCES agent_folders(id),
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  system_prompt   TEXT,
  model           VARCHAR(250),         -- provider:model-name
  recursion_limit INTEGER DEFAULT 25,
  webhook_token   VARCHAR(100) UNIQUE,  -- dbuilder_xxx
  is_favorited    BOOLEAN DEFAULT false,
  is_mcp_active   BOOLEAN DEFAULT false,
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 에이전트 버전 이력
CREATE TABLE agent_versions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id      UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  version_no    INTEGER NOT NULL,        -- 0, 1, 2, ...
  system_prompt TEXT,
  model         VARCHAR(250),
  snapshot      JSONB,                  -- 전체 설정 스냅샷
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- 도구
CREATE TABLE tools (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  name        VARCHAR(255) NOT NULL,
  type        VARCHAR(50) NOT NULL,     -- builtin|custom|mcp_remote|mcp_local|http
  description TEXT,
  config      JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- 에이전트 ↔ 도구 연결
CREATE TABLE agent_tools (
  agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
  tool_id  UUID REFERENCES tools(id) ON DELETE CASCADE,
  position INTEGER DEFAULT 0,
  PRIMARY KEY (agent_id, tool_id)
);

-- 미들웨어 설정
CREATE TABLE agent_middlewares (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  middleware_type VARCHAR(100) NOT NULL,  -- e.g. ModelRetryMiddleware
  position        INTEGER DEFAULT 0,
  config          JSONB NOT NULL DEFAULT '{}',
  enabled         BOOLEAN DEFAULT true
);

-- 스킬
CREATE TABLE agent_skills (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  filename   VARCHAR(255) NOT NULL,
  content    TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Secrets
CREATE TABLE secrets (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id),
  scope      VARCHAR(20) DEFAULT 'user',  -- user|workspace
  key_name   VARCHAR(255) NOT NULL,
  key_value  TEXT NOT NULL,               -- 암호화 저장 (Fernet)
  UNIQUE(user_id, scope, key_name)
);

-- 오프너 (대화 시작 버튼)
CREATE TABLE agent_openers (
  id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  text     TEXT NOT NULL,
  position INTEGER DEFAULT 0
);

-- 대화 / 메시지
CREATE TABLE conversations (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id   UUID NOT NULL REFERENCES agents(id),
  user_id    UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            VARCHAR(20) NOT NULL,  -- user|assistant|tool
  content         TEXT,
  tool_calls      JSONB,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- RAG 문서
CREATE TABLE agent_documents (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  filename   VARCHAR(255),
  content    TEXT,
  embedding  vector(1536),
  page_no    INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON agent_documents USING ivfflat (embedding vector_cosine_ops);

-- 스케줄
CREATE TABLE agent_schedules (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  cron_expr  VARCHAR(100) NOT NULL,
  input_msg  TEXT,
  enabled    BOOLEAN DEFAULT true,
  last_run   TIMESTAMPTZ
);
```

---

## 9. API 엔드포인트 전체 목록

### 9.1 인증

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/auth/login` | JWT 로그인 (email + password) |
| POST | `/api/v1/auth/refresh` | JWT 갱신 |
| GET  | `/api/v1/auth/me` | 현재 사용자 정보 |

### 9.2 에이전트

| Method | Path | 설명 |
|--------|------|------|
| GET    | `/api/v1/agents` | 에이전트 목록 (폴더 트리) |
| POST   | `/api/v1/agents` | 에이전트 생성 |
| GET    | `/api/v1/agents/{id}` | 에이전트 상세 |
| PUT    | `/api/v1/agents/{id}` | 에이전트 수정 |
| DELETE | `/api/v1/agents/{id}` | 에이전트 삭제 |
| POST   | `/api/v1/agents/{id}/duplicate` | 에이전트 복제 |
| POST   | `/api/v1/agents/{id}/favorite` | 즐겨찾기 토글 |
| POST   | `/api/v1/agents/import` | 에이전트 JSON 임포트 |
| GET    | `/api/v1/agents/{id}/export` | 에이전트 JSON 내보내기 |
| GET    | `/api/v1/agents/{id}/versions` | 버전 이력 |
| POST   | `/api/v1/agents/{id}/versions/{v}/restore` | 버전 복원 |
| POST   | `/api/v1/agents/{id}/chat` | SSE 스트리밍 채팅 |
| POST   | `/api/v1/agents/{id}/fix` | Fix 에이전트 실행 |
| GET    | `/api/v1/agents/{id}/snippet` | 코드 스니펫 생성 |
| POST   | `/api/v1/agents/{id}/webhook` | Webhook 수신 (Bearer 토큰) |

### 9.3 도구 / 모델 / 미들웨어 / 스킬

| Method | Path | 설명 |
|--------|------|------|
| GET    | `/api/v1/tools` | 도구 목록 |
| POST   | `/api/v1/tools` | 도구 생성 |
| PUT    | `/api/v1/tools/{id}` | 도구 수정 |
| DELETE | `/api/v1/tools/{id}` | 도구 삭제 |
| GET    | `/api/v1/models` | 모델 목록 (공급사별) |
| GET    | `/api/v1/models/providers` | 공급사 목록 |
| POST   | `/api/v1/models/providers` | 공급사 추가 (Custom) |
| GET    | `/api/v1/middlewares` | 미들웨어 목록 + 스키마 |
| GET    | `/api/v1/secrets` | Secrets 목록 |
| POST   | `/api/v1/secrets` | Secret 등록 |
| DELETE | `/api/v1/secrets/{id}` | Secret 삭제 |
| POST   | `/api/v1/agents/{id}/skills` | 스킬 추가 |
| DELETE | `/api/v1/agents/{id}/skills/{sk}` | 스킬 삭제 |
| POST   | `/api/v1/agents/{id}/skills/gen` | AI로 스킬 생성 |

### 9.4 OpenAI 호환 API

| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/chat/completions` | OpenAI 호환 채팅 API (에이전트 실행) |
| GET  | `/v1/models` | 사용 가능 에이전트 목록 |

---

## 10. 단계별 구현 계획

> **전략:** 각 Phase 완료 후 아래 "🤖 AI 작업 지시"를 Cursor / Claude Code에 붙여넣기

---

### Phase 0 — 프로젝트 셋업 & 인프라 (2일)

**목표:** 개발 환경 + Docker Compose + DB 초기화
**산출물:** docker-compose.yml, alembic 마이그레이션, 기본 앱 실행

**작업 목록:**
- Docker Compose: postgres(pgvector), redis, backend, frontend, celery worker
- PostgreSQL pgvector 확장 활성화
- FastAPI 기본 앱 + 헬스체크 엔드포인트
- SQLAlchemy + Alembic 셋업, 전체 DB 스키마 마이그레이션
- Next.js 14 기본 앱 + Tailwind CSS + shadcn/ui
- JWT 인증 (login, refresh, me 엔드포인트)
- .env 템플릿

#### 🤖 AI 작업 지시 — Phase 0

```
1. docker-compose.yml을 작성하라. services: postgres(pgvector:pg16), redis:7-alpine,
   backend(FastAPI), frontend(Next.js 14), celery. postgres에 POSTGRES_DB, USER, PASSWORD
   환경변수 설정, pgvector 확장 자동 활성화.

2. backend/app/database.py: SQLAlchemy 2.0 async 엔진, 세션 팩토리, Base 선언.

3. alembic 초기화 후 8장의 전체 DB 스키마(users, agents, agent_versions, agent_folders,
   tools, agent_tools, agent_middlewares, agent_skills, secrets, agent_openers,
   conversations, messages, agent_documents(vector 타입), agent_schedules)를
   한 번에 마이그레이션하라.

4. backend/app/routers/auth.py: POST /api/v1/auth/login (이메일+비밀번호, JWT 반환),
   GET /api/v1/auth/me (Bearer 토큰 검증). python-jose + bcrypt 사용.

5. frontend: Next.js 14 App Router 셋업, Tailwind + shadcn/ui 설치, /login 페이지(JWT
   로그인 폼), 로그인 후 /app으로 리다이렉트, JWT를 localStorage에 저장하는 useAuth 훅.
```

---

### Phase 1 — 에이전트 CRUD + 사이드바 (3일)

**목표:** 에이전트 생성/수정/삭제 + 폴더 트리 사이드바
**산출물:** /app 페이지, 사이드바 UI, 에이전트 CRUD API

**작업 목록:**
- 에이전트 CRUD API (POST/GET/PUT/DELETE /api/v1/agents)
- 폴더 CRUD API + 폴더별 에이전트 트리 응답
- 즐겨찾기 토글 API + 프론트엔드 반영
- 에이전트 임포트/내보내기 (JSON)
- 사이드바: 폴더 트리, 새 에이전트, 즐겨찾기, 에이전트 가져오기
- 버전 자동 저장 (PUT 에이전트 시 이전 버전 스냅샷)
- Webhook 토큰 자동 생성 (`dbuilder_` + nanoid)

#### 🤖 AI 작업 지시 — Phase 1

```
1. GET /api/v1/agents: 현재 사용자의 에이전트를 폴더별 트리 구조로 반환
   (folder_id, 미분류=null 포함).

2. POST /api/v1/agents: 에이전트 생성 시 webhook_token을
   "dbuilder_" + secrets.token_urlsafe(24)로 자동 생성.

3. PUT /api/v1/agents/{id}: 수정 전 현재 상태를 agent_versions에 스냅샷 저장
   (version_no 자동 증가).

4. agent_folders CRUD API 구현 (GET/POST/PUT/DELETE /api/v1/folders).

5. POST /api/v1/agents/import, GET /api/v1/agents/{id}/export: 에이전트 전체
   설정(tools, middlewares, openers 포함)을 JSON으로 직렬화/역직렬화.

6. 프론트엔드 /app/layout.tsx에 Sidebar.tsx 구현: 폴더 트리 아코디언, 에이전트
   클릭 시 /app/agent/{id}/edit으로 이동, 에이전트 오른쪽 클릭 컨텍스트 메뉴
   (이름변경, 삭제, 즐겨찾기).

7. /app/page.tsx: 에이전트 목록 그리드 카드 뷰, "새 에이전트" 버튼,
   "에이전트 가져오기" 파일 업로드 버튼.
```

---

### Phase 2 — 에이전트 편집기 UI (4일)

**목표:** 에이전트 편집기 좌측 패널 + 우측 7탭 UI
**산출물:** /app/agent/[id]/edit 페이지 전체

**작업 목록:**
- 좌측: 이름, 설명, 시스템 프롬프트(폼/비주얼 뷰), 서브 에이전트, 모델 선택, 도구 추가, 미들웨어 추가
- 시스템 프롬프트: 폼 뷰(섹션별 입력) + 비주얼 뷰(마크다운 렌더링) + 에디터 확장(전체화면 모달)
- 우측 탭: Fix에이전트, 테스트, 오프너, 파일, 스킬, 스케줄, 설정
- 오프너: 추가/삭제/정렬, 최대 12개 제한
- 설정 탭: Recursion Limit(1-1000), Webhook 토큰 표시, MCP 서버 토글
- 실시간 자동저장 (debounce 1초)

#### 🤖 AI 작업 지시 — Phase 2

```
1. /app/agent/[id]/edit/page.tsx: 좌우 분할 레이아웃. 좌측(설정 패널, 스크롤 가능),
   우측(탭 패널). 실시간 자동저장(useEffect + debounce).

2. SystemPromptEditor.tsx: 상단 탭으로 "폼 | 비주얼" 전환. 폼 뷰는 textarea 직접
   입력, 비주얼 뷰는 react-markdown으로 렌더링. "에디터 확장" 버튼 클릭 시 전체화면 Dialog.

3. OpenersTab.tsx: 오프너 목록(최대 12개 표시, 추가 시 12개 초과 경고), 각 오프너
   텍스트 입력 + 삭제 버튼, drag-to-reorder(@dnd-kit/core 사용).

4. SettingsTab.tsx: Recursion Limit 슬라이더(1-1000, 기본 25), Webhook 토큰 표시
   (복사 버튼), MCP 서버 활성화 토글, 위험 구역(에이전트 삭제 버튼).

5. VersionHistoryPanel.tsx: GET /api/v1/agents/{id}/versions로 버전 목록, 클릭 시
   해당 버전 내용 미리보기, "이 버전으로 복원" 버튼.
```

---

### Phase 3 — LangGraph 에이전트 실행 + SSE 채팅 (4일)

**목표:** LangGraph 실행 엔진 + SSE 스트리밍 채팅
**산출물:** 테스트 탭 채팅, /api/v1/agents/{id}/chat

**작업 목록:**
- LangGraph StateGraph 동적 빌더 (도구/모델에 따라 그래프 구성)
- 미들웨어 파이프라인 (before/after invoke)
- `provider:model-name` 형식으로 LLM 동적 로딩
- SSE 스트리밍: FastAPI StreamingResponse + astream_events
- 프론트엔드: SSE 수신, 토큰 스트리밍 표시
- 서브 에이전트 도구 (에이전트를 다른 에이전트의 도구로 실행)

**핵심 패턴:**

```python
# agents/builder.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

def build_agent_graph(agent_config: dict, tools: list) -> StateGraph:
    model = load_model(agent_config["model"])  # provider:model-name 파싱
    model_with_tools = model.bind_tools(tools)
    tool_node = ToolNode(tools)

    def should_continue(state):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", lambda s: {"messages": [model_with_tools.invoke(s["messages"])]})
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile()

# routers/chat.py
from fastapi.responses import StreamingResponse
import json

@router.post("/{agent_id}/chat")
async def chat(agent_id: str, body: ChatRequest, user=Depends(get_current_user)):
    async def event_stream():
        graph = await build_agent_graph_from_db(agent_id)
        async for event in graph.astream_events({"messages": body.messages}, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"].content
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

#### 🤖 AI 작업 지시 — Phase 3

```
1. agents/builder.py: build_agent_graph(agent_config, tools) 구현.
   agent_config["model"]에서 "provider:model-name" 파싱, load_model() 함수로
   공급사별 LangChain LLM 반환(Anthropic/OpenAI/Google/Azure 지원).

2. agents/executor.py: AgentExecutor 클래스. middlewares 리스트를 순서대로
   before_invoke → graph.astream_events → after_invoke 실행.

3. POST /api/v1/agents/{id}/chat: StreamingResponse(event_stream()),
   media_type="text/event-stream". SSE 형식:
   data: {"type":"token","content":"..."}\n\n, 종료 시 data: [DONE]\n\n.

4. 프론트엔드 TestTab.tsx: fetch + ReadableStream으로 SSE 수신, 토큰 단위로
   메시지에 append. 사용자 메시지 전송, 에이전트 응답 스트리밍 표시, 대화 히스토리 유지.

5. tools/builtin.py: arxiv(arxiv 라이브러리), duckduckgo(duckduckgo-search),
   wikipedia(wikipedia-api), sequential_thinking(chain-of-thought wrapper)
   LangChain Tool로 래핑.

6. 서브 에이전트 도구: create_subagent_tool(agent_id) → LangChain Tool, invoke 시
   해당 에이전트의 chat 실행(재귀 방지: recursion_limit 확인).
```

---

### Phase 4 — 도구/모델 레지스트리 + Secrets (3일)

**목표:** 도구 관리 UI + 모델 레지스트리 + Secrets 관리
**산출물:** /app/tools/* 페이지 (5탭: 도구, 모델, 미들웨어, 스킬, Secrets)

**작업 목록:**
- 도구 탭: 도구 목록 + 생성/수정/삭제, 유형별 폼(MCP 원격/로컬/HTTP)
- 모델 탭: 7개 공급사, `provider:model-name` 형식 표시
- 미들웨어 탭: 18종 목록 + JSON Schema 기반 설정 폼
- 스킬 탭: 스킬 파일 업로드 + AI 어시스턴트로 생성
- Secrets 탭: Key-Value 등록/수정/삭제, scope 선택
- MCP 도구 실행기: mcp.stdio / mcp.sse 방식 지원
- HTTP 도구: OpenAPI 스펙 파싱 또는 수동 설정

#### 🤖 AI 작업 지시 — Phase 4

```
1. 프론트엔드 /app/tools 페이지: 상단 탭 네비게이션(도구|모델|미들웨어|스킬|Secrets).
   각 탭은 독립 컴포넌트.

2. 도구 탭: GET /api/v1/tools 목록, 유형 배지(built-in/custom/mcp_remote/mcp_local/http),
   "도구 추가" 버튼 → Dialog. Dialog 내 type 선택에 따라 동적 폼 표시(MCP Local이면
   명령어 입력, HTTP이면 URL+메서드+헤더).

3. 모델 탭: GET /api/v1/models/providers로 공급사 그룹화, 각 공급사 섹션에 모델 목록.
   "Custom 공급사 추가" 버튼(base_url + api_key 입력).

4. 미들웨어 탭: GET /api/v1/middlewares로 18종 목록+스키마. 각 미들웨어 카드에
   "설정" 버튼 → JSON Schema 기반 자동 폼 생성.

5. Secrets 탭: GET /api/v1/secrets로 현재 등록된 키 목록(값은 마스킹). "키 추가" 버튼,
   Key/Value/Scope 입력 폼. 에이전트 실행 시 secrets를 환경변수로 주입하는 백엔드 로직.

6. tools/mcp_remote.py: mcp 라이브러리(pip install mcp)로 stdio/sse 방식 MCP 서버
   연결, 도구 목록 가져오기, 도구 호출 래핑.
```

---

### Phase 5 — Fix 에이전트 + 미들웨어 구현 + RAG (4일)

**목표:** Fix 에이전트, 18종 미들웨어, RAG 파일 검색
**산출물:** Fix 탭 동작, 미들웨어 파이프라인, 파일 탭 RAG

**작업 목록:**
- Fix 에이전트: 자연어로 시스템 프롬프트+도구+오프너 원자적 변경
- 핵심 미들웨어: ModelRetryMiddleware, SummarizationMiddleware, ModelFallbackMiddleware, HumanInTheLoopMiddleware, PIIMiddleware
- 추가 미들웨어: ContextEditingMiddleware, TodoListMiddleware, ToolCallLimitMiddleware, ModelCallLimitMiddleware
- Anthropic 미들웨어: PromptCachingMiddleware, MemoryMiddleware
- RAG: 파일 업로드 → 청크 분할 → 임베딩 → pgvector 저장
- 채팅 시 RAG 자동 검색 + 출처 페이지 표시

#### 🤖 AI 작업 지시 — Phase 5

```
1. POST /api/v1/agents/{id}/fix: 사용자 자연어 지시를 받아 별도의 "Fix LLM"을 호출.
   Fix LLM은 structured output으로
   {system_prompt, tools_to_add, tools_to_remove, openers} JSON 반환.
   DB 원자적 업데이트.

2. middleware/builtin/retry.py (ModelRetryMiddleware): after_invoke에서 LLM 오류 감지,
   exponential backoff로 max_retries 재시도.

3. middleware/builtin/summarization.py (SummarizationMiddleware): before_invoke에서
   messages 토큰 수 계산, threshold 초과 시 이전 메시지를 요약 LLM으로 압축.

4. middleware/builtin/fallback.py (ModelFallbackMiddleware): 주 모델 실패 시
   fallback_models 리스트를 순서대로 시도.

5. middleware/builtin/pii.py (PIIMiddleware): presidio-analyzer 라이브러리로
   PII 감지 및 마스킹.

6. POST /api/v1/agents/{id}/files: 파일 업로드 → pypdf/docx2txt로 텍스트 추출 →
   langchain.text_splitter로 청크 분할 → OpenAI/Anthropic 임베딩 API →
   agent_documents 테이블 저장. 채팅 시 사용자 메시지를 임베딩하여
   cosine_similarity 상위 5개 청크를 시스템 프롬프트에 주입.
```

---

### Phase 6 — 스케줄링 + 코드 스니펫 API + 마무리 (3일)

**목표:** Celery 스케줄, OpenAI 호환 API, 전체 통합 테스트
**산출물:** 완성된 프로덕션 가능 시스템

**작업 목록:**
- Celery 스케줄: Cron 표현식 파싱, 에이전트 자동 실행
- Background Mode: Celery 비동기 실행 + 결과 저장
- `/v1/chat/completions`: OpenAI 호환 API (Bearer dbuilder_xxx)
- 코드 스니펫 생성기: Python/TypeScript/cURL/LangChain 코드 자동 생성
- MCP 서버: 에이전트별 MCP 서버 엔드포인트 활성화
- Webhook 수신기: n8n/Dify 연동 테스트
- 전체 E2E 테스트 + Docker 프로덕션 빌드

#### 🤖 AI 작업 지시 — Phase 6

```
1. Celery Beat 스케줄러: agent_schedules 테이블의 cron_expr을 읽어 동적 스케줄 등록.
   celery.beat_schedule에 에이전트별 태스크 추가/제거 API.

2. POST /v1/chat/completions: OpenAI API 형식 그대로 구현. Authorization 헤더의
   Bearer 토큰으로 에이전트 ID 조회. stream=true이면 SSE, false이면 일반 JSON 응답.
   model 필드는 "agent-{uuid}" 형식.

3. GET /api/v1/agents/{id}/snippet?lang={python|typescript|curl|langchain}:
   해당 에이전트 ID와 Webhook 토큰을 사용하는 코드 스니펫 문자열 반환.

4. MCP 서버 엔드포인트: GET /api/v1/agents/{id}/mcp (에이전트가 MCP 서버로 동작,
   Claude Desktop 연동용). is_mcp_active=true인 에이전트만 활성화.

5. Webhook 수신: POST /api/v1/agents/{id}/webhook,
   Authorization: Bearer {webhook_token} 검증, 메시지를 Celery 태스크로 비동기 실행,
   결과를 callback_url에 POST.

6. 통합 테스트: 에이전트 생성 → 도구 추가(duckduckgo) → 미들웨어 추가
   (ModelRetryMiddleware) → 채팅 테스트(SSE) → Fix 에이전트로 오프너 추가 →
   코드 스니펫 생성 → OpenAI 호환 API로 외부 호출 전 과정 검증.
```

---

## 11. 핵심 구현 패턴 레퍼런스

### 11.1 provider:model-name → LangChain LLM 변환

```python
# agents/builder.py
def load_model(model_str: str):
    """provider:model-name 형식을 LangChain LLM으로 변환"""
    provider, model_name = model_str.split(":", 1)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name)
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name)
    elif provider == "azure":
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(deployment_name=model_name)
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, base_url="https://openrouter.ai/api/v1")
    elif provider == "bizrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, base_url="https://api.bizrouter.ai/v1")
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

### 11.2 Secrets 환경변수 주입

```python
async def inject_secrets(user_id: str, db: AsyncSession) -> dict:
    secrets = await db.execute(
        select(Secret).where(
            (Secret.user_id == user_id) | (Secret.scope == "workspace")
        )
    )
    env_vars = {s.key_name: decrypt(s.key_value) for s in secrets.scalars()}
    return env_vars

@contextmanager
def with_secrets(env_vars: dict):
    old = {k: os.environ.get(k) for k in env_vars}
    os.environ.update(env_vars)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
```

### 11.3 SSE 프론트엔드 수신 패턴

```typescript
// lib/sse.ts
export async function streamChat(
  agentId: string,
  messages: Message[],
  onToken: (token: string) => void,
  onDone: () => void
) {
  const res = await fetch(`/api/v1/agents/${agentId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${getToken()}`
    },
    body: JSON.stringify({ messages })
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    for (const line of text.split("\n")) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6);
        if (data === "[DONE]") { onDone(); return; }
        const { content } = JSON.parse(data);
        if (content) onToken(content);
      }
    }
  }
}
```

### 11.4 Fix 에이전트 Structured Output

```python
# agents/fix_agent.py
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic

class FixResult(BaseModel):
    system_prompt: str | None = None
    tools_to_add: list[str] = []       # tool IDs
    tools_to_remove: list[str] = []    # tool IDs
    openers: list[str] | None = None   # None=변경없음
    explanation: str = ""

async def run_fix_agent(agent: Agent, instruction: str) -> FixResult:
    llm = ChatAnthropic(model="claude-sonnet-4-6").with_structured_output(FixResult)
    prompt = f"""현재 에이전트 설정:
시스템 프롬프트: {agent.system_prompt}
도구: {[t.name for t in agent.tools]}
오프너: {[o.text for o in agent.openers]}

사용자 지시: {instruction}

위 지시에 따라 에이전트를 수정하라."""
    return await llm.ainvoke(prompt)
```

### 11.5 OpenAI 호환 API 구현

```python
# routers/snippets.py
from fastapi import APIRouter, Header
from pydantic import BaseModel

class ChatCompletionRequest(BaseModel):
    model: str           # "agent-{uuid}"
    messages: list[dict]
    stream: bool = False

@router.post("/v1/chat/completions")
async def openai_compatible_chat(
    body: ChatCompletionRequest,
    authorization: str = Header(...)
):
    token = authorization.removeprefix("Bearer ")
    agent = await get_agent_by_webhook_token(token)
    if body.stream:
        return StreamingResponse(openai_sse_stream(agent, body.messages),
                                  media_type="text/event-stream")
    else:
        result = await run_agent_sync(agent, body.messages)
        return {
            "id": f"chatcmpl-{uuid4()}",
            "object": "chat.completion",
            "model": body.model,
            "choices": [{"message": {"role": "assistant", "content": result}}]
        }
```

---

## 12. 환경변수 & 배포 가이드

### 12.1 필수 환경변수 (.env)

```bash
# 데이터베이스
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/deepagent
REDIS_URL=redis://localhost:6379/0

# 보안
SECRET_KEY=your-super-secret-key-min-32-chars
ENCRYPTION_KEY=fernet-key-for-secrets-encryption

# AI 모델 API 키 (사용하는 공급사만 설정)
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
GOOGLE_API_KEY=xxx
AZURE_OPENAI_API_KEY=xxx
AZURE_OPENAI_ENDPOINT=https://xxx.openai.azure.com/
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
OPENROUTER_API_KEY=sk-or-xxx

# 앱 설정
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
DEFAULT_MODEL=anthropic:claude-sonnet-4-6
```

### 12.2 Docker Compose 실행

```bash
# 전체 서비스 시작
docker-compose up -d

# DB 마이그레이션
docker-compose exec backend alembic upgrade head

# 첫 번째 관리자 계정 생성
docker-compose exec backend python -c "
from app.database import sync_session
from app.models.user import User
from app.utils.auth import hash_password
db = sync_session()
db.add(User(email='admin@company.com', name='Admin', hashed_pw=hash_password('password'), is_admin=True))
db.commit()"

# 로그 확인
docker-compose logs -f backend
docker-compose logs -f celery
```

### 12.3 개발 환경 (로컬)

```bash
# 백엔드
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Celery Worker
celery -A app.tasks worker --loglevel=info
celery -A app.tasks beat --loglevel=info  # 스케줄러

# 프론트엔드
cd frontend
npm install
npm run dev

# 접속
# 프론트엔드: http://localhost:3000
# 백엔드 API 문서: http://localhost:8000/docs
```

> ⚠️ **주의 (내부 전용):** 외부에 절대 노출 금지. SECRET_KEY와 ENCRYPTION_KEY는 반드시 강력한 랜덤 값으로 설정. 프로덕션에서는 HTTPS 필수.

---

## 부록 A — 의존성 목록

### 백엔드 (requirements.txt)

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
alembic==1.13.0
python-jose[cryptography]==3.3.0
bcrypt==4.1.2
pydantic==2.7.0
pydantic-settings==2.2.0
python-multipart==0.0.9

# LangChain / LangGraph
langgraph==0.2.0
langchain==0.3.0
langchain-anthropic==0.3.0
langchain-openai==0.2.0
langchain-google-genai==2.0.0
langchain-community==0.3.0

# 도구
arxiv==2.1.0
duckduckgo-search==6.1.0
wikipedia-api==0.6.0
mcp==1.0.0

# Celery
celery[redis]==5.4.0

# 파일 처리 (RAG)
pypdf==4.2.0
docx2txt==0.8
langchain-text-splitters==0.3.0
presidio-analyzer==2.2.35

# 암호화
cryptography==42.0.0
```

### 프론트엔드 주요 패키지 (package.json)

```json
{
  "dependencies": {
    "next": "14.2.0",
    "react": "^18",
    "typescript": "^5",
    "tailwindcss": "^3",
    "@radix-ui/react-*": "...",
    "react-markdown": "^9",
    "@dnd-kit/core": "^6",
    "@dnd-kit/sortable": "^8",
    "zustand": "^4",
    "swr": "^2",
    "date-fns": "^3"
  }
}
```

---

## 부록 B — 구현 체크리스트

```
[ ] Phase 0: Docker Compose 실행, DB 마이그레이션, JWT 로그인
[ ] Phase 1: 에이전트 CRUD, 폴더 트리, 사이드바, 버전 저장
[ ] Phase 2: 에이전트 편집기 전체 UI (7탭, 시스템 프롬프트 폼/비주얼)
[ ] Phase 3: LangGraph 실행 엔진, SSE 채팅, built-in 도구 5종
[ ] Phase 4: 도구/모델/미들웨어/스킬/Secrets 관리 UI
[ ] Phase 5: Fix 에이전트, 미들웨어 파이프라인, RAG 파일 검색
[ ] Phase 6: Celery 스케줄, OpenAI 호환 API, Webhook, 전체 통합 테스트
```
