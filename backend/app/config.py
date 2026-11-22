"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPERLENS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PaperLens AI"
    environment: str = "development"
    secret_key: str = "dev-only-secret-change-me-in-production"
    database_url: str = "sqlite:///./data/paperlens.db"
    storage_dir: Path = Path("./data/storage")
    max_upload_mb: int = 50
    max_pdf_pages: int = 400
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "PAPERLENS_DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: int = 180
    request_timeout_seconds: int = 300
    agent_max_rounds: int = 8
    agent_max_tool_calls: int = 20
    agent_timeout_seconds: int = 240
    agent_tool_timeout_seconds: int = 45
    agent_token_budget: int = 30000
    vision_provider: str = "none"
    vision_model: str | None = None
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 600
    encryption_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PAPERLENS_ENCRYPTION_KEY"),
    )
    demo_seed: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


DEFAULT_SECRET = "dev-only-secret-change-me-in-production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        if settings.secret_key == DEFAULT_SECRET or len(settings.secret_key) < 32:
            raise RuntimeError(
                "PAPERLENS_SECRET_KEY must be set to a unique value of at least 32 characters in production"
            )
        if settings.cors_origins.strip() == "*":
            raise RuntimeError("Wildcard CORS is not allowed in production; list explicit origins")
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        if db_path.parent and str(db_path.parent) not in {"", "."}:
            db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        Path("./data").mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()