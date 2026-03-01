from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: int
    email: EmailStr


class FolderIn(BaseModel):
    name: str


class AgentIn(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    folder_id: int | None = None
    model: str = "openai:gpt-4o-mini"


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    folder_id: int | None = None
    model: str | None = None
    is_favorite: bool | None = None
    recursion_limit: int | None = None
    mcp_enabled: bool | None = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ToolIn(BaseModel):
    name: str
    type: str
    config: dict = {}


class SecretIn(BaseModel):
    key_name: str
    key_value: str
    scope: str = "user"


class FixRequest(BaseModel):
    instruction: str


class ScheduleIn(BaseModel):
    cron_expr: str
    enabled: bool = True
    payload: dict = {}
