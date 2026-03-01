from fastapi import FastAPI

from .routers.auth import router as auth_router
from .routers.agents import router as agents_router
from .routers.folders import router as folders_router
from .routers.chat import router as chat_router
from .routers.tools import router as tools_router
from .routers.models_registry import router as models_router
from .routers.secrets import router as secrets_router
from .routers.schedules import router as schedules_router
from .routers.openai_compat import router as openai_router

app = FastAPI(title="deep-agents backend")


@app.get("/health")
async def health():
    return {"ok": True}


app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(folders_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(models_router)
app.include_router(secrets_router)
app.include_router(schedules_router)
app.include_router(openai_router)
