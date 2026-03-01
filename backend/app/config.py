from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "deep-agents"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60
    database_url: str = "postgresql+asyncpg://deep_agents:deep_agents@localhost:5432/deep_agents"
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
