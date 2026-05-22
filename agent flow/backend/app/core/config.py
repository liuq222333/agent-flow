from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://agent_flow:agent_flow_dev@localhost:5432/agent_flow"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Field(default=Path("../storage/uploads"))
    secret_encryption_key: str = "dev-only-change-me-32-bytes-minimum"
    mock_user_id: int = 1
    auth_mode: str = "mock"
    api_bearer_token: str | None = None
    default_model_provider: str = "deepseek"
    openai_api_key: str | None = None
    openai_api_key_secret: str = "openai_api_key"
    deepseek_api_key: str | None = None
    deepseek_api_key_secret: str = "deepseek_api_key"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str = "deepseek-v4-flash"
    deepseek_default_context_window: int = 1_000_000
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_content_types: str = (
        "text/plain,text/markdown,application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    cors_allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def allowed_upload_types(self) -> set[str]:
        return {
            content_type.strip().lower()
            for content_type in self.allowed_upload_content_types.split(",")
            if content_type.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
