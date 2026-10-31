import json
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.modules.ai.export_schema import ai_generation_json_schema
from app.modules.ai.providers import create_provider, get_ai_provider, use_ai_provider
from app.modules.ai.providers.anthropic import AnthropicProvider
from app.modules.ai.providers.mock import MockAIProvider
from app.modules.ai.providers.openrouter import OpenRouterProvider
from tests.ai.helpers import ScriptedAIProvider
from tests.building.helpers import REPO_ROOT

AI_SCHEMA_PATH = REPO_ROOT / "packages" / "schema" / "generated" / "ai-generation.schema.json"


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "jwt_secret": "s" * 32,
    }
    return Settings(_env_file=None, **(base | overrides))


def test_mock_is_the_default_provider_in_tests() -> None:
    provider = get_ai_provider()
    assert isinstance(provider, MockAIProvider) and provider.name == "mock"


def test_anthropic_provider_is_built_from_configuration_without_network() -> None:
    settings = _settings(
        ai_provider="anthropic",
        anthropic_api_key=SecretStr("sk-test"),
        ai_model="claude-opus-5",
        ai_effort="high",
    )
    provider = create_provider(settings)
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic" and provider.model == "claude-opus-5"


def test_openrouter_provider_is_built_from_configuration_without_network() -> None:
    settings = _settings(
        ai_provider="openrouter",
        openrouter_api_key=SecretStr("sk-or-test-secret"),
        openrouter_model="anthropic/claude-opus-5.5",
    )
    provider = create_provider(settings)
    assert isinstance(provider, OpenRouterProvider)
    assert provider.name == "openrouter" and provider.model == "anthropic/claude-opus-5.5"
    assert "sk-or-test-secret" not in repr(provider)
    assert "sk-or-test-secret" not in repr(settings)


def test_openrouter_model_comes_from_configuration() -> None:
    settings = _settings(
        ai_provider="openrouter",
        openrouter_api_key=SecretStr("sk-or-test"),
        openrouter_model="some-vendor/other-model",
    )
    assert create_provider(settings).model == "some-vendor/other-model"


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"openrouter_model": "anthropic/claude-opus-5.5"}, "OPENROUTER_API_KEY"),
        (
            {"openrouter_model": "anthropic/claude-opus-5.5", "openrouter_api_key": ""},
            "OPENROUTER_API_KEY",
        ),
        ({"openrouter_api_key": SecretStr("sk-or-test-secret")}, "OPENROUTER_MODEL"),
    ],
)
def test_openrouter_settings_fail_fast_without_key_or_model(
    overrides: dict[str, Any], missing: str
) -> None:
    with pytest.raises(ValidationError) as info:
        _settings(ai_provider="openrouter", **overrides)
    assert missing in str(info.value)
    assert "sk-or-test-secret" not in str(info.value)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(ai_provider="gpt-somewhere")


def test_override_hook_restores_the_configured_provider() -> None:
    scripted = ScriptedAIProvider()
    with use_ai_provider(scripted):
        assert get_ai_provider() is scripted
    assert isinstance(get_ai_provider(), MockAIProvider)


def test_committed_ai_json_schema_is_up_to_date() -> None:
    # packages/schema is generated from Pydantic; regenerate with `pnpm schema`.
    committed = json.loads(AI_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == ai_generation_json_schema()
