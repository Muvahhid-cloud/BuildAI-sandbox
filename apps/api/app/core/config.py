"""Application settings, loaded from environment variables (and `.env` in development).

Required settings have no default: the app refuses to start without them.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _default_data_dir() -> Path:
    """Repo `data/` when running from a checkout; `/data` inside the Docker image."""
    here = Path(__file__).resolve()
    repo_data = here.parents[4] / "data" if len(here.parents) > 4 else None
    return repo_data if repo_data is not None and repo_data.is_dir() else Path("/data")


class Settings(BaseSettings):
    # Repo-root .env (when run from apps/api) then a local override; missing files are ignored.
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    # Shared data: material library, fixtures (and later catalogs / rules profiles).
    data_dir: Path = Field(default_factory=_default_data_dir)

    # PostgreSQL, async driver: postgresql+asyncpg://user:pass@host:5432/db
    database_url: PostgresDsn

    # Auth
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    cookie_secure: bool = True

    # Comma-separated list of allowed browser origins (only needed when the web app
    # calls the API cross-origin; the Next.js dev server proxies /api by default).
    cors_origins: Annotated[list[str], NoDecode] = []

    # Product defaults (decided 2026-09-27, see docs/roadmap.md decisions log)
    default_region_code: str = "KZ-ALA"
    default_currency: str = Field(default="KZT", pattern=r"^[A-Z]{3}$")
    default_rules_profile: str = "generic-residential@1"

    # AI (docs/ai-pipeline.md). "mock" is the deterministic offline interpreter (development,
    # tests, CI); it is refused in production. Tests always use "mock".
    ai_provider: Literal["mock", "anthropic", "openrouter"] = "mock"
    ai_model: str | None = None  # anthropic: e.g. claude-opus-5 (required)
    anthropic_api_key: SecretStr | None = None  # backend only, never logged or sent to clients
    anthropic_base_url: str | None = None
    # OpenRouter (OpenAI-compatible gateway): key and model, e.g. anthropic/claude-opus-5.5.
    openrouter_api_key: SecretStr | None = None  # backend only, never logged or sent to clients
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    ai_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    ai_max_retries: int = Field(default=1, ge=0, le=5)  # transient errors, inside the SDK
    ai_max_repairs: int = Field(default=1, ge=0, le=2)  # repair calls after invalid output
    ai_max_output_tokens: int = Field(default=16000, ge=1000, le=64000)
    ai_max_prompt_chars: int = Field(default=4000, ge=100, le=20000)
    ai_generations_per_hour: int = Field(default=30, ge=1, le=10000)  # per user
    # Log the full prompt text (off by default: only length and a hash are logged).
    ai_log_prompts: bool = False

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, v: PostgresDsn) -> PostgresDsn:
        if v.scheme != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.environment is Environment.PRODUCTION:
            if "change-me" in self.jwt_secret:
                raise ValueError("JWT_SECRET still has the .env.example placeholder value")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.ai_provider == "mock":
                raise ValueError("AI_PROVIDER=mock is for development/tests only, not production")
        return self

    @model_validator(mode="after")
    def _ai_provider_config(self) -> "Settings":
        if self.ai_provider == "anthropic":
            if self.anthropic_api_key is None or not self.anthropic_api_key.get_secret_value():
                raise ValueError("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
            if not self.ai_model:
                raise ValueError("AI_PROVIDER=anthropic requires AI_MODEL (e.g. claude-opus-5)")
        if self.ai_provider == "openrouter":
            if self.openrouter_api_key is None or not self.openrouter_api_key.get_secret_value():
                raise ValueError("AI_PROVIDER=openrouter requires OPENROUTER_API_KEY")
            if not self.openrouter_model:
                raise ValueError(
                    "AI_PROVIDER=openrouter requires OPENROUTER_MODEL "
                    "(e.g. anthropic/claude-opus-5.5)"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
