"""Runtime-only executor configuration supplied by a Claude Desktop MCPB."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


MODEL_ENV = "HERMIT_DESKTOP_EXECUTOR_MODEL"
BASE_URL_ENV = "HERMIT_DESKTOP_EXECUTOR_BASE_URL"
API_KEY_ENV = "HERMIT_DESKTOP_EXECUTOR_API_KEY"
PROVIDER_NAME = "claude-desktop"


def executor_values(environ: Mapping[str, str] | None = None) -> tuple[str, str, str]:
    source = os.environ if environ is None else environ
    return (
        str(source.get(MODEL_ENV, "") or "").strip(),
        str(source.get(BASE_URL_ENV, "") or "").strip(),
        str(source.get(API_KEY_ENV, "") or "").strip(),
    )


def executor_config_error(environ: Mapping[str, str] | None = None) -> str | None:
    """Return a user-facing error for an incomplete Desktop executor form."""
    model, base_url, _api_key = executor_values(environ)
    if base_url and not model:
        return "Claude Desktop executor URL requires an executor model."
    return None


def apply_desktop_executor_override(settings: dict[str, Any], environ: Mapping[str, str] | None = None) -> None:
    """Apply the extension form without writing API credentials to settings.json.

    A blank form preserves the user's existing settings.  Supplying only a
    model is useful for a locally configured executor; supplying an endpoint
    creates an ephemeral, explicit OpenAI-compatible provider route.
    """
    model, base_url, api_key = executor_values(environ)
    if not model:
        return

    route: dict[str, str] = {"model": model}
    if base_url:
        providers = settings.get("providers")
        providers = dict(providers) if isinstance(providers, dict) else {}
        provider = {"base_url": base_url}
        if api_key:
            provider["api_key"] = api_key
        providers[PROVIDER_NAME] = provider
        settings["providers"] = providers
        route["provider"] = PROVIDER_NAME
    settings["routing"] = {"priority_models": [route]}
