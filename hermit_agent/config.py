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
        {"model": "gpt-5.4", "reasoning_effort": "medium"},
        {"model": "glm-5.1"},
        {"model": "qwen3-coder:30b"}
      ]
    }
  }
"""
from __future__ import annotations

import json
import os
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
    "codex_command": "codex",
    "codex_default_model": "gpt-5.4",
    "codex_reasoning_effort": "medium",
    "model": "qwen3-coder:30b",
    "routing": {
        "priority_models": [
            {"model": "gpt-5.4", "reasoning_effort": "medium"},
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
    "HERMIT_CODEX_COMMAND": "codex_command",
    "HERMIT_CODEX_DEFAULT_MODEL": "codex_default_model",
    "HERMIT_CODEX_REASONING_EFFORT": "codex_reasoning_effort",
    "Z_AI_API_KEY": "llm_api_key",
    "HERMIT_LANG": "response_language",
    "HERMIT_COMPACT_INSTRUCTIONS": "compact_instructions",
    "HERMIT_SEED_HANDOFF": "seed_handoff",
    "HERMIT_AUTO_WRAP": "auto_wrap",
    "HERMIT_OLLAMA_MAX_LOADED": "ollama_max_loaded",
    "HERMIT_EXTERNAL_MAX_CONCURRENT": "external_max_concurrent",
}


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
    return dict(block) if isinstance(block, dict) else {}


def _is_local_ollama_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True
    return host in _LOCAL_HOSTS


def is_model_configured(model: str, cfg: dict[str, Any]) -> bool:
    platform = _resolve_platform_for_model(model)
    if platform == "local":
        ollama_url = str(cfg.get("ollama_url", DEFAULTS["ollama_url"]) or DEFAULTS["ollama_url"])
        if not _is_local_ollama_url(ollama_url):
            return True
        return shutil.which("ollama") is not None

    if is_codex_model_name(model):
        codex_command = str(cfg.get("codex_command", DEFAULTS["codex_command"]) or DEFAULTS["codex_command"])
        return shutil.which(codex_command) is not None

    if platform is None:
        return False

    cred = get_provider_cred(cfg, platform)
    return bool(cred.get("base_url")) and bool(cred.get("api_key"))


def is_codex_model_name(model: str) -> bool:
    lowered = (model or "").strip().lower()
    return (
        lowered.startswith("codex/")
        or lowered == "codex"
        or "-codex" in lowered
        or lowered == "gpt-5.4"
        or lowered.startswith("gpt-5.4-")
    )


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
        else:
            continue

        if not model or model in seen_models:
            continue
        if available_only and not is_model_configured(model, cfg):
            continue

        entry = {"model": model}
        if reasoning_effort:
            entry["reasoning_effort"] = reasoning_effort
        deduped.append(entry)
        seen_models.add(model)
    return deduped


def get_primary_model(cfg: dict[str, Any], *, available_only: bool = False) -> str:
    routing_models = get_routing_priority_models(cfg, available_only=available_only)
    if routing_models:
        return routing_models[0]["model"]
    return str(cfg.get("model", "") or "")


def select_llm_endpoint(model: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """Resolves (base_url, api_key) for *model*.

    Ollama models (`name:tag`) route to `ollama_url`; external models
    look up their platform block in `providers`. Returns `('', '')`
    when nothing is configured so callers can raise.
    """
    platform = _resolve_platform_for_model(model)
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
    _BOOL_KEYS = {"seed_handoff", "auto_wrap"}
    for k in _BOOL_KEYS:
        val = settings.get(k)
        if isinstance(val, str):
            settings[k] = val.lower() not in {"0", "false", "no", "off"}

    # 5. Coerce integer keys (env vars arrive as strings)
    _INT_KEYS = {"ollama_max_loaded", "external_max_concurrent", "max_turns"}
    for k in _INT_KEYS:
        val = settings.get(k)
        if isinstance(val, str):
            try:
                settings[k] = int(val)
            except ValueError:
                settings[k] = DEFAULTS[k]

    # 6. Lift legacy flat provider fields (llm_url + llm_api_key) into
    #    the `providers` dict. Heuristic: if the URL is z.ai, attach to
    #    the "z.ai" block; otherwise drop under "legacy" so the data is
    #    not lost. Existing `providers` entries win.
    legacy_url = settings.pop("llm_url", "") or ""
    legacy_key = settings.pop("llm_api_key", "") or ""
    providers = settings.get("providers") or {}
    if not isinstance(providers, dict):
        providers = {}
    if legacy_url or legacy_key:
        slug = "z.ai" if "z.ai" in legacy_url else "legacy"
        block = providers.setdefault(slug, {})
        block.setdefault("base_url", legacy_url)
        block.setdefault("api_key", legacy_key)
    settings["providers"] = providers

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
