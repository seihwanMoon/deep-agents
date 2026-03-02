from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers.auth import router as auth_router
from .routers.agents import router as agents_router
from .routers.folders import router as folders_router
from .routers.chat import router as chat_router
from .routers.tools import router as tools_router
from .routers.models_registry import router as models_router
from .routers.middlewares import router as middlewares_router
from .routers.secrets import router as secrets_router
from .routers.schedules import router as schedules_router
from .routers.openai_compat import router as openai_router


app = FastAPI(title="deep-agents backend")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def ui_home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app/agent/{agent_id}/edit")
async def ui_agent_editor(agent_id: int):
    _ = agent_id
    return FileResponse(STATIC_DIR / "agent-editor.html")


@app.get("/health")
async def health():
    return {"ok": True}


app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(folders_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(models_router)
app.include_router(middlewares_router)
app.include_router(secrets_router)
app.include_router(schedules_router)
app.include_router(openai_router)
