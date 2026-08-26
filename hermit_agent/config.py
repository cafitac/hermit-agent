"""HermitAgent settings management.

Follows Claude's settings.json pattern.

Priority order (lowest → highest):
  1. Defaults (DEFAULTS)
  2. Global settings (~/.hermit/settings.json)
  3. Project local settings (<cwd>/.hermit/settings.json)
  4. Environment variables (HERMIT_*)
  5. CLI arguments (bridge.py --gateway-url, etc.)

Example settings file:
  {
    "gateway_url": "http://localhost:8765",
    "gateway_api_key": "your-key",
    "model": "qwen3-coder:30b",
    "max_turns": 200,
    "routing": {
      "priority_models": [
        {"model": "glm-5.1"},
        {"model": "qwen3-coder:30b"}
      ]
    }
  }
"""
from __future__ import annotations

import json
import os
import re
import shutil
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

GLOBAL_SETTINGS_PATH = Path.home() / ".hermit" / "settings.json"
LOCAL_SETTINGS_RELPATH = ".hermit/settings.json"

DEFAULTS: dict[str, Any] = {
    "gateway_url": "http://localhost:8765",
    "gateway_api_key": "",
    # Per-platform upstream credentials. Keyed by platform slug
    # (`z.ai`, `anthropic`, `openai`, …). Each block carries at least
    # `base_url` + `api_key`; Anthropic-compat paths can add
    # `anthropic_base_url`. See `get_provider_cred(cfg, platform)`.
    "providers": {},
    "ollama_url": "http://localhost:11434/v1",
    "orchestration": {
        "mode": "single",
        "max_agents": 3,
        "allow_parallel_writes": False,
    },
    "model": "qwen3-coder:30b",
    "routing": {
        "priority_models": [
            {"model": "glm-5.1"},
            {"model": "qwen3-coder:30b"},
        ]
    },
    "max_turns": 200,
    "response_language": "auto",
    # Free-form extra directive appended to the compaction prompt. Empty string
    # disables injection — matches upstream "compact instructions" behaviour.
    "compact_instructions": "",
    "seed_handoff": True,
    "auto_wrap": True,
    # Gateway admission control. `ollama_max_loaded` caps how many
    # distinct models we allow ollama to hold in memory concurrently —
    # a new chat request targeting an unloaded model past this budget
    # is rejected fast rather than risking an OOM swap. External
    # providers (z.ai, openai, …) queue instead of failing.
    "ollama_max_loaded": 1,
    "external_max_concurrent": 10,
    # Local LLM backend auto-detection (v2-ready explicit string).
    # Values: "mlx" | "llama_cpp" | "ollama" | None
    "local_backend": None,
    # Base URL for the active local backend (supersedes ollama_url when set).
    "local_llm_url": None,
    # Model name required for non-ollama backends (MLX, llama.cpp).
    "local_model": None,
}

# Legacy flat fields accepted on read so pre-migration settings still
# load. `load_settings()` lifts them into `providers` and callers stop
# seeing them. Removed from DEFAULTS so new installs don't reintroduce
# the flat shape.
_LEGACY_KEYS = {"llm_url", "llm_api_key"}

_KNOWN_KEYS = set(DEFAULTS) | _LEGACY_KEYS

_ENV_MAP = {
    "HERMIT_GATEWAY_URL": "gateway_url",
    "HERMIT_GATEWAY_API_KEY": "gateway_api_key",
    "HERMIT_MODEL": "model",
    # Legacy flat aliases are accepted at env level and lifted into
    # `providers` during load_settings(), matching the settings.json
    # migration path.
    "HERMIT_LLM_URL": "llm_url",
    "HERMIT_API_KEY": "llm_api_key",
    "HERMIT_OLLAMA_URL": "ollama_url",
    "Z_AI_API_KEY": "llm_api_key",
    "HERMIT_LANG": "response_language",
    "HERMIT_COMPACT_INSTRUCTIONS": "compact_instructions",
    "HERMIT_SEED_HANDOFF": "seed_handoff",
    "HERMIT_AUTO_WRAP": "auto_wrap",
    "HERMIT_OLLAMA_MAX_LOADED": "ollama_max_loaded",
    "HERMIT_EXTERNAL_MAX_CONCURRENT": "external_max_concurrent",
}

_BOOL_KEYS = ("seed_handoff", "auto_wrap")
_INT_KEYS = ("ollama_max_loaded", "external_max_concurrent", "max_turns")


# Model-prefix → platform slug. Duplicates gateway/routing.py rules on
# purpose: this layer is reachable from standalone callers that never
# import the gateway package.
_MODEL_PREFIX_PLATFORM: list[tuple[str, str]] = [
    ("glm-", "z.ai"),
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
]

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}


def _resolve_platform_for_model(model: str) -> str | None:
    if not model:
        return None
    if ":" in model:
        return "local"
    for prefix, slug in _MODEL_PREFIX_PLATFORM:
        if model.startswith(prefix):
            return slug
    return None


def get_provider_cred(cfg: dict[str, Any], platform: str) -> dict[str, Any]:
    providers = cfg.get("providers") or {}
    block = providers.get(platform)
    if not isinstance(block, dict):
        return {}
    credential = dict(block)
    api_key_env = credential.get("api_key_env")
    if not credential.get("api_key") and isinstance(api_key_env, str) and api_key_env.strip():
        credential["api_key"] = os.environ.get(api_key_env.strip(), "")
    return credential


def _is_local_ollama_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True
    return host in _LOCAL_HOSTS


def is_model_configured(model: str, cfg: dict[str, Any], *, provider: str | None = None) -> bool:
    platform = provider or _resolve_platform_for_model(model)
    if platform == "local":
        ollama_url = str(cfg.get("ollama_url", DEFAULTS["ollama_url"]) or DEFAULTS["ollama_url"])
        if not _is_local_ollama_url(ollama_url):
            return True
        return shutil.which("ollama") is not None

    if platform is None:
        return False

    cred = get_provider_cred(cfg, platform)
    return bool(cred.get("base_url")) and bool(cred.get("api_key"))


def get_routing_priority_models(cfg: dict[str, Any], *, available_only: bool = False) -> list[dict[str, str]]:
    routing = cfg.get("routing") or {}
    raw_priority_models = routing.get("priority_models") if isinstance(routing, dict) else None
    candidates = raw_priority_models if isinstance(raw_priority_models, list) else DEFAULTS["routing"]["priority_models"]

    deduped: list[dict[str, str]] = []
    seen_models: set[str] = set()
    for item in candidates:
        if isinstance(item, str):
            model = item.strip()
            reasoning_effort = None
        elif isinstance(item, dict):
            model = str(item.get("model", "") or "").strip()
            reasoning_effort = str(item.get("reasoning_effort", "") or "").strip() or None
            provider = str(item.get("provider", "") or "").strip() or None
        else:
            continue

        if isinstance(item, str):
            provider = None

        if not model or model in seen_models:
            continue
        if available_only:
            configured = (
                is_model_configured(model, cfg, provider=provider)
                if provider
                else is_model_configured(model, cfg)
            )
            if not configured:
                continue

        entry = {"model": model}
        if reasoning_effort:
            entry["reasoning_effort"] = reasoning_effort
        if provider:
            entry["provider"] = provider
        deduped.append(entry)
        seen_models.add(model)
    return deduped


def get_primary_model(cfg: dict[str, Any], *, available_only: bool = False) -> str:
    routing_models = get_routing_priority_models(cfg, available_only=available_only)
    if routing_models:
        return routing_models[0]["model"]
    return str(cfg.get("model", "") or "")


def select_llm_endpoint(model: str, cfg: dict[str, Any], *, provider: str | None = None) -> tuple[str, str]:
    """Resolves (base_url, api_key) for *model*.

    Ollama models (`name:tag`) route to `ollama_url`; external models
    look up their platform block in `providers`. Returns `('', '')`
    when nothing is configured so callers can raise.
    """
    platform = provider or _resolve_platform_for_model(model)
    if platform == "local":
        return cfg.get("ollama_url", DEFAULTS["ollama_url"]), ""
    if platform is None:
        return "", ""
    cred = get_provider_cred(cfg, platform)
    return cred.get("base_url", ""), cred.get("api_key", "")


def _load_json(path: Path) -> dict[str, Any]:
    """Reads a JSON file and returns only known keys. Returns an empty dict on failure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in _KNOWN_KEYS}
    except Exception:
        return {}


def load_settings(cwd: str | None = None) -> dict[str, Any]:
    """Merges and returns settings in global → local → environment variable order.

    CLI arguments are processed by argparse after this function.
    """
    settings = dict(DEFAULTS)

    # 1. Global settings (~/.hermit/settings.json)
    if GLOBAL_SETTINGS_PATH.exists():
        settings.update(_load_json(GLOBAL_SETTINGS_PATH))

    # 2. Project local settings (<cwd>/.hermit/settings.json)
    if cwd:
        local_path = Path(cwd) / LOCAL_SETTINGS_RELPATH
        if local_path.exists():
            settings.update(_load_json(local_path))

    # 3. Environment variables (overrides only if not empty)
    for env_key, setting_key in _ENV_MAP.items():
        val = os.environ.get(env_key, "")
        if val:
            settings[setting_key] = val

    # 4. Coerce boolean keys (env vars arrive as strings)
    for k in _BOOL_KEYS:
        bool_val: Any = settings.get(k)
        if isinstance(bool_val, str):
            settings[k] = bool_val.lower() not in {"0", "false", "no", "off"}

    # 5. Coerce integer keys (env vars arrive as strings)
    for k in _INT_KEYS:
        int_val: Any = settings.get(k)
        if isinstance(int_val, str):
            try:
                settings[k] = int(int_val)
            except ValueError:
                settings[k] = DEFAULTS[k]

    # 6. Lift legacy flat provider fields (llm_url + llm_api_key) into
    #    the `providers` dict. Heuristic: if the URL is z.ai, attach to
    #    the "z.ai" block; otherwise drop under "legacy" so the data is
    #    not lost. Existing `providers` entries win.
    raw_legacy_url = settings.pop("llm_url", "")
    raw_legacy_key = settings.pop("llm_api_key", "")
    legacy_url = str(raw_legacy_url or "")
    legacy_key = str(raw_legacy_key or "")
    providers = settings.get("providers") or {}
    if not isinstance(providers, dict):
        providers = {}
    if legacy_url or legacy_key:
        slug = "z.ai" if "z.ai" in legacy_url else "legacy"
        block = providers.setdefault(slug, {})
        block.setdefault("base_url", legacy_url)
        block.setdefault("api_key", legacy_key)
    settings["providers"] = providers

    # Claude Desktop's MCPB form is passed as process-local environment
    # variables.  Apply it after legacy migration so it can replace routing
    # without ever writing a sensitive key to ~/.hermit/settings.json.
    from .desktop_config import apply_desktop_executor_override

    apply_desktop_executor_override(settings)

    routing = settings.get("routing")
    if not isinstance(routing, dict):
        settings["routing"] = dict(DEFAULTS["routing"])
    else:
        priority_models = routing.get("priority_models")
        if not isinstance(priority_models, list):
            routing["priority_models"] = list(DEFAULTS["routing"]["priority_models"])
        settings["routing"] = routing

    return settings


def settings_path(global_: bool = True, cwd: str | None = None) -> Path:
    """Returns the settings file path (for writing)."""
    if global_:
        return GLOBAL_SETTINGS_PATH
    if cwd:
        return Path(cwd) / LOCAL_SETTINGS_RELPATH
    return GLOBAL_SETTINGS_PATH


def init_settings_file(global_: bool = True, cwd: str | None = None) -> Path:
    """Creates the settings file with default values if it does not exist. Returns the path."""
    path = settings_path(global_=global_, cwd=cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps(
                {k: v for k, v in DEFAULTS.items() if k != "gateway_api_key"},
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
    return path


def configure_openai_compatible_provider(
    *, model: str, base_url: str, api_key_env: str, provider_name: str = "openai-compatible"
) -> Path:
    """Store only an environment-variable reference for an executor secret."""
    model = model.strip()
    base_url = base_url.strip().rstrip("/")
    api_key_env = api_key_env.strip()
    provider_name = provider_name.strip()
    parsed = urlparse(base_url)
    if not model:
        raise ValueError("--model is required")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute http(s) URL")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise ValueError("--api-key-env must be a valid environment variable name")
    if not provider_name:
        raise ValueError("--provider is required")

    path = init_settings_file()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot safely update {path}; repair the JSON settings file first.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Cannot safely update {path}; settings must be a JSON object.")

    providers = payload.get("providers")
    providers = dict(providers) if isinstance(providers, dict) else {}
    providers[provider_name] = {"base_url": base_url, "api_key_env": api_key_env}
    payload["providers"] = providers

    routing = payload.get("routing")
    existing = routing.get("priority_models", []) if isinstance(routing, dict) else []
    preserved = [
        item
        for item in existing
        if not (isinstance(item, dict) and item.get("model") == model and item.get("provider") == provider_name)
    ]
    payload["routing"] = {"priority_models": [{"model": model, "provider": provider_name}, *preserved]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def apply_detected_backend(
    cfg: dict[str, Any],
    info: LocalRuntimeInfo,
    all_detected: list[LocalRuntimeInfo],
) -> dict[str, Any]:
    """Merge auto-detected backend info into settings dict.

    Sets: local_backend, local_llm_url, local_model, local_backend_auto_detected, local_backends_available
    """
    from .local_runtime import BACKEND_OLLAMA

    out = dict(cfg)
    out["local_backend"] = info.backend
    out["local_llm_url"] = info.base_url
    # For Ollama, keep existing ollama_url synced
    if info.backend == BACKEND_OLLAMA and info.base_url:
        out["ollama_url"] = info.base_url
    # model_hint is optional; don't overwrite an explicit setting
    if info.model_hint and not cfg.get("local_model"):
        out["local_model"] = info.model_hint
    out["local_backend_auto_detected"] = True
    out["local_backends_available"] = [
        {"backend": r.backend, "available": r.available, "base_url": r.base_url}
        for r in all_detected
        if r.available
    ]
    return out
