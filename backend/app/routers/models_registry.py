from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/models", tags=["models"])

PROVIDERS = {
    "openai": ["gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    "google": ["gemini-1.5-pro", "gemini-1.5-flash"],
    "azure": ["gpt-4o"],
    "openrouter": ["openai/gpt-4o-mini"],
    "bizrouter": ["bizrouter-general"],
    "xai": ["grok-beta"],
}


@router.get("/providers")
async def model_providers():
    return {"providers": [{"name": k, "models": [f"{k}:{m}" for m in v]} for k, v in PROVIDERS.items()]}
