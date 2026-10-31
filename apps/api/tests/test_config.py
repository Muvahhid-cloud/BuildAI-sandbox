from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "jwt_secret": "s" * 32,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_valid_settings_and_kz_defaults() -> None:
    s = _settings(cors_origins="http://a.test, http://b.test")
    assert s.default_currency == "KZT"
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_rejects_sync_driver() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        _settings(database_url="postgresql://u:p@localhost/db")


def test_production_rejects_placeholder_secret_and_insecure_cookie() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        _settings(environment="production", jwt_secret="change-me-" + "x" * 40, cookie_secure=True)
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        _settings(environment="production", cookie_secure=False)
    assert _settings(environment="production", cookie_secure=True, **REAL_AI).is_production


REAL_AI: dict[str, Any] = {
    "ai_provider": "anthropic",
    "anthropic_api_key": "test-key",
    "ai_model": "claude-opus-5",
}


def test_production_refuses_the_mock_ai_provider() -> None:
    with pytest.raises(ValidationError, match="AI_PROVIDER=mock"):
        _settings(environment="production", cookie_secure=True, ai_provider="mock")


def test_anthropic_provider_requires_key_and_model() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        _settings(ai_provider="anthropic", anthropic_api_key=None, ai_model="claude-opus-5")
    with pytest.raises(ValidationError, match="AI_MODEL"):
        _settings(ai_provider="anthropic", anthropic_api_key="k", ai_model=None)
    s = _settings(**REAL_AI)
    assert s.anthropic_api_key is not None
    assert "test-key" not in repr(s)  # secret never rendered


def test_unknown_ai_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(ai_provider="openai")


def test_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        _settings(jwt_secret="short")
