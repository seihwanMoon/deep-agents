from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/v1/middlewares", tags=["middlewares"])

MIDDLEWARE_REGISTRY = [
    {"key": "ModelRetryMiddleware", "provider": "builtin", "category": "reliability", "config_schema": {"max_retries": {"type": "integer", "default": 2}, "backoff_seconds": {"type": "number", "default": 0.5}}},
    {"key": "SummarizationMiddleware", "provider": "builtin", "category": "context", "config_schema": {"threshold_tokens": {"type": "integer", "default": 5000}}},
    {"key": "ModelFallbackMiddleware", "provider": "builtin", "category": "reliability", "config_schema": {"fallback_models": {"type": "array", "items": "string"}}},
    {"key": "HumanInTheLoopMiddleware", "provider": "builtin", "category": "safety", "config_schema": {"approval_required": {"type": "boolean", "default": True}}},
    {"key": "PIIMiddleware", "provider": "builtin", "category": "safety", "config_schema": {"masking_strategy": {"type": "string", "default": "replace"}}},
    {"key": "ContextEditingMiddleware", "provider": "builtin", "category": "context", "config_schema": {}},
    {"key": "TodoListMiddleware", "provider": "builtin", "category": "productivity", "config_schema": {}},
    {"key": "ToolCallLimitMiddleware", "provider": "builtin", "category": "control", "config_schema": {"limit": {"type": "integer", "default": 10}}},
    {"key": "ModelCallLimitMiddleware", "provider": "builtin", "category": "control", "config_schema": {"limit": {"type": "integer", "default": 8}}},
    {"key": "RateLimitMiddleware", "provider": "builtin", "category": "control", "config_schema": {"rpm": {"type": "integer", "default": 60}}},
    {"key": "GuardrailMiddleware", "provider": "builtin", "category": "safety", "config_schema": {}},
    {"key": "ToolChoiceMiddleware", "provider": "builtin", "category": "tools", "config_schema": {}},
    {"key": "PromptCachingMiddleware", "provider": "anthropic", "category": "provider", "config_schema": {}},
    {"key": "MemoryMiddleware", "provider": "anthropic", "category": "provider", "config_schema": {"window_size": {"type": "integer", "default": 12}}},
    {"key": "CitationsMiddleware", "provider": "anthropic", "category": "provider", "config_schema": {}},
    {"key": "ReasoningBudgetMiddleware", "provider": "anthropic", "category": "provider", "config_schema": {"budget_tokens": {"type": "integer", "default": 512}}},
    {"key": "ToolUseConsolidationMiddleware", "provider": "anthropic", "category": "provider", "config_schema": {}},
    {"key": "OpenAIResponsesModeMiddleware", "provider": "openai", "category": "provider", "config_schema": {"mode": {"type": "string", "default": "responses"}}},
]


def _filter_middlewares(provider: str | None, category: str | None, q: str | None):
    items = MIDDLEWARE_REGISTRY
    if provider:
        provider = provider.strip().lower()
        items = [m for m in items if m["provider"].lower() == provider]
    if category:
        category = category.strip().lower()
        items = [m for m in items if m["category"].lower() == category]
    if q:
        token = q.strip().lower()
        items = [m for m in items if token in m["key"].lower()]
    return items


@router.get("")
async def list_middlewares(
    provider: str | None = Query(default=None),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    user: User = Depends(get_current_user),
):
    items = _filter_middlewares(provider=provider, category=category, q=q)
    return {
        "items": items,
        "total": len(items),
        "filters": {"provider": provider, "category": category, "q": q},
    }


@router.get("/{middleware_key}")
async def get_middleware_detail(middleware_key: str, user: User = Depends(get_current_user)):
    for item in MIDDLEWARE_REGISTRY:
        if item["key"].lower() == middleware_key.lower():
            return item
    raise HTTPException(status_code=404, detail="Middleware not found")
