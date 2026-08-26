"""Provider-credentials schema: nested `providers` dict in settings.json.

The old flat shape (`llm_url` + `llm_api_key` at the top level) is replaced
by a per-platform block:

    {
      "providers": {
        "z.ai": {
          "base_url": "https://api.z.ai/api/coding/paas/v4",
          "api_key": "...",
          "anthropic_base_url": "https://api.z.ai/api/anthropic"  # optional
        }
      }
    }

Known model prefixes still work, and custom OpenAI-compatible providers can be
selected explicitly in each routing entry.
"""
from __future__ import annotations

import json


from hermit_agent.config import (
    DEFAULTS,
    configure_openai_compatible_provider,
    get_provider_cred,
    get_routing_priority_models,
    load_settings,
    select_llm_endpoint,
)


# ── get_provider_cred ──────────────────────────────────────────────────────


def test_get_provider_cred_returns_block_for_configured_platform():
    cfg = {
        "providers": {
            "z.ai": {
                "base_url": "https://api.z.ai/api/coding/paas/v4",
                "api_key": "secret",
            }
        }
    }
    assert get_provider_cred(cfg, "z.ai") == {
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "api_key": "secret",
    }


def test_get_provider_cred_returns_empty_dict_for_unconfigured_platform():
    cfg = {"providers": {}}
    assert get_provider_cred(cfg, "z.ai") == {}


def test_get_provider_cred_missing_providers_key_returns_empty():
    assert get_provider_cred({}, "z.ai") == {}


# ── select_llm_endpoint reads from providers dict ─────────────────────────


def test_select_llm_endpoint_ollama_unchanged():
    cfg = {"ollama_url": "http://localhost:11434/v1"}
    url, key = select_llm_endpoint("qwen3-coder:30b", cfg)
    assert url == "http://localhost:11434/v1"
    assert key == ""


def test_select_llm_endpoint_external_reads_providers():
    cfg = {
        "providers": {
            "z.ai": {
                "base_url": "https://api.z.ai/api/coding/paas/v4",
                "api_key": "k-123",
            }
        }
    }
    url, key = select_llm_endpoint("glm-5.1", cfg)
    assert url == "https://api.z.ai/api/coding/paas/v4"
    assert key == "k-123"


def test_explicit_provider_routes_an_arbitrary_openai_compatible_model(monkeypatch):
    cfg = {
        "providers": {
            "budget-provider": {
                "base_url": "https://llm.example.com/v1",
                "api_key_env": "BUDGET_PROVIDER_API_KEY",
            }
        },
        "routing": {
            "priority_models": [{"model": "coder-small", "provider": "budget-provider"}]
        },
    }
    monkeypatch.setenv("BUDGET_PROVIDER_API_KEY", "budget-key")

    assert get_provider_cred(cfg, "budget-provider")["api_key"] == "budget-key"
    assert select_llm_endpoint("coder-small", cfg, provider="budget-provider") == (
        "https://llm.example.com/v1",
        "budget-key",
    )
    assert get_routing_priority_models(cfg, available_only=True) == [
        {"model": "coder-small", "provider": "budget-provider"}
    ]


def test_select_llm_endpoint_unknown_model_falls_back_to_empty():
    """No provider configured, unknown prefix — return ('', '') so caller can raise."""
    cfg = {"providers": {}}
    url, key = select_llm_endpoint("gpt-4", cfg)
    assert (url, key) == ("", "")


# ── Legacy migration: flat llm_url/llm_api_key auto-lifted ─────────────────


def test_load_settings_migrates_legacy_flat_fields_into_providers(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "gateway_url": "http://localhost:8765",
                "llm_url": "https://api.z.ai/api/coding/paas/v4",
                "llm_api_key": "legacy-key",
                "model": "glm-5.1",
            }
        )
    )
    monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", settings_path)
    cfg = load_settings()
    assert cfg["providers"]["z.ai"]["base_url"] == "https://api.z.ai/api/coding/paas/v4"
    assert cfg["providers"]["z.ai"]["api_key"] == "legacy-key"


def test_load_settings_with_fresh_providers_no_regression(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "gateway_url": "http://localhost:8765",
                "model": "glm-5.1",
                "providers": {
                    "z.ai": {
                        "base_url": "https://api.z.ai/api/coding/paas/v4",
                        "api_key": "new-key",
                    }
                },
            }
        )
    )
    monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", settings_path)
    cfg = load_settings()
    assert cfg["providers"]["z.ai"]["api_key"] == "new-key"
    url, key = select_llm_endpoint("glm-5.1", cfg)
    assert url == "https://api.z.ai/api/coding/paas/v4"
    assert key == "new-key"


def test_providers_empty_by_default():
    assert DEFAULTS["providers"] == {}


def test_configure_openai_compatible_provider_stores_only_environment_reference(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", settings_path)

    path = configure_openai_compatible_provider(
        model="coder-small",
        base_url="https://llm.example.com/v1/",
        api_key_env="BUDGET_PROVIDER_API_KEY",
        provider_name="budget",
    )

    payload = json.loads(path.read_text())
    assert payload["providers"]["budget"] == {
        "base_url": "https://llm.example.com/v1",
        "api_key_env": "BUDGET_PROVIDER_API_KEY",
    }
    assert payload["routing"]["priority_models"][0] == {"model": "coder-small", "provider": "budget"}
    assert '"api_key":' not in json.dumps(payload)
