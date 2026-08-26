"""Readiness checks for executor routes used by the MCP gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from .config import get_provider_cred, get_routing_priority_models


@dataclass(frozen=True)
class ExecutorReadiness:
    """A safe, actionable summary without exposing credentials."""

    status: str
    routes: tuple[str, ...]
    guidance: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def _ollama_tags_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunparse(parsed._replace(path=f"{path}/api/tags", params="", query="", fragment=""))


def _same_ollama_model(installed: str, requested: str) -> bool:
    return installed == requested or installed.removesuffix(":latest") == requested.removesuffix(":latest")


def _ollama_route_status(model: str, cfg: dict[str, Any]) -> tuple[bool, str, str]:
    base_url = str(cfg.get("ollama_url", "http://localhost:11434/v1") or "")
    try:
        response = httpx.get(_ollama_tags_url(base_url), timeout=3.0)
        payload = response.json() if response.status_code == 200 else {}
    except Exception:
        return False, f"Ollama unavailable for {model}", f"Start Ollama, then run `ollama pull {model}`."

    installed = [str(item.get("name", "")) for item in payload.get("models", []) if isinstance(item, dict)]
    if any(_same_ollama_model(name, model) for name in installed):
        return True, f"Ollama model ready: {model}", ""
    return False, f"Ollama model missing: {model}", f"Run `ollama pull {model}`."


def inspect_executor_readiness(cfg: dict[str, Any]) -> ExecutorReadiness:
    """Check that at least one configured executor can accept a task.

    Remote providers are validated for the required model, URL, and resolved
    environment-secret reference. They are not network-probed here so `doctor`
    remains fast and never sends an API key outside of task execution.
    """

    routes = get_routing_priority_models(cfg)
    details: list[str] = []
    guidance: list[str] = []
    any_ready = False

    for route in routes:
        model = route["model"]
        provider_name = route.get("provider")
        if ":" in model and not provider_name:
            ready, detail, hint = _ollama_route_status(model, cfg)
            any_ready = any_ready or ready
            details.append(detail)
            if hint:
                guidance.append(hint)
            continue

        provider_name = provider_name or ("z.ai" if model.startswith("glm-") else "openai" if model.startswith("gpt-") else "anthropic" if model.startswith("claude-") else "")
        provider = get_provider_cred(cfg, provider_name) if provider_name else {}
        base_url = str(provider.get("base_url", "") or "").strip()
        api_key = str(provider.get("api_key", "") or "").strip()
        api_key_env = str((cfg.get("providers", {}).get(provider_name, {}) if isinstance(cfg.get("providers"), dict) else {}).get("api_key_env", "") or "").strip()

        if base_url and api_key:
            any_ready = True
            details.append(f"OpenAI-compatible provider ready: {provider_name} / {model}")
            continue

        missing: list[str] = []
        if not base_url:
            missing.append("base URL")
        if not api_key:
            missing.append(f"environment variable {api_key_env}" if api_key_env else "API key environment variable")
        details.append(f"Provider not ready: {provider_name or model} ({', '.join(missing)} missing)")
        guidance.append(
            "Run `hermit configure --model <model> --base-url <url> --api-key-env <NAME>`, then export <NAME>."
        )

    if any_ready:
        return ExecutorReadiness("ready", tuple(details), tuple(dict.fromkeys(guidance)))
    if not routes:
        details.append("No executor route configured")
    if not guidance:
        guidance.append(
            "Run `hermit configure --model <model> --base-url <url> --api-key-env <NAME>`, or install Ollama and pull a coder model."
        )
    return ExecutorReadiness("needs-configuration", tuple(details), tuple(dict.fromkeys(guidance)))
