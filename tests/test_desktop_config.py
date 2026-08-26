from __future__ import annotations

from hermit_agent.desktop_config import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MODEL_ENV,
    PROVIDER_NAME,
    apply_desktop_executor_override,
    executor_config_error,
)


def test_desktop_executor_form_creates_an_ephemeral_openai_compatible_route() -> None:
    settings = {"providers": {}, "routing": {"priority_models": [{"model": "qwen3-coder:30b"}]}}

    apply_desktop_executor_override(
        settings,
        {MODEL_ENV: "coder-small", BASE_URL_ENV: "https://llm.example.com/v1", API_KEY_ENV: "secret"},
    )

    assert settings["routing"] == {"priority_models": [{"model": "coder-small", "provider": PROVIDER_NAME}]}
    assert settings["providers"][PROVIDER_NAME] == {"base_url": "https://llm.example.com/v1", "api_key": "secret"}


def test_blank_desktop_form_preserves_existing_settings() -> None:
    settings = {"routing": {"priority_models": [{"model": "existing"}]}}

    apply_desktop_executor_override(settings, {})

    assert settings == {"routing": {"priority_models": [{"model": "existing"}]}}


def test_desktop_endpoint_requires_a_model() -> None:
    assert executor_config_error({BASE_URL_ENV: "https://llm.example.com/v1"}) == (
        "Claude Desktop executor URL requires an executor model."
    )
