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

Routing is still by model prefix — `glm-*` → `z.ai`, `:` → local ollama.
"""
from __future__ import annotations

import json


from hermit_agent.config import (
    DEFAULTS,
    get_provider_cred,
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
