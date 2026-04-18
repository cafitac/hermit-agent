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
    "max_turns": 200
  }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

GLOBAL_SETTINGS_PATH = Path.home() / ".hermit" / "settings.json"
LOCAL_SETTINGS_RELPATH = ".hermit/settings.json"

DEFAULTS: dict[str, Any] = {
    "gateway_url": "http://localhost:8765",
    "gateway_api_key": "",
    "llm_url": "http://localhost:11434/v1",
    "llm_api_key": "",
    "ollama_url": "http://localhost:11434/v1",
    "model": "qwen3-coder:30b",
    "max_turns": 200,
    "response_language": "auto",
    # Free-form extra directive appended to the compaction prompt. Empty string
    # disables injection — matches upstream "compact instructions" behaviour.
    "compact_instructions": "",
    "seed_handoff": True,
    "auto_wrap": True,
}

_KNOWN_KEYS = set(DEFAULTS)

_ENV_MAP = {
    "HERMIT_GATEWAY_URL": "gateway_url",
    "HERMIT_GATEWAY_API_KEY": "gateway_api_key",
    "HERMIT_MODEL": "model",
    "HERMIT_LLM_URL": "llm_url",
    "HERMIT_API_KEY": "llm_api_key",
    "HERMIT_OLLAMA_URL": "ollama_url",
    "Z_AI_API_KEY": "llm_api_key",
    "HERMIT_LANG": "response_language",
    "HERMIT_COMPACT_INSTRUCTIONS": "compact_instructions",
    "HERMIT_SEED_HANDOFF": "seed_handoff",
    "HERMIT_AUTO_WRAP": "auto_wrap",
}


def select_llm_endpoint(model: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """Selects an LLM endpoint by model name and returns (base_url, api_key).

    The `name:tag` pattern (e.g., `qwen3:8b`) routes to local ollama,
    while others (e.g., `glm-5.1`) use the configured `llm_url`.
    """
    if model and ":" in model:
        return cfg.get("ollama_url", DEFAULTS["ollama_url"]), ""
    return cfg.get("llm_url", DEFAULTS["llm_url"]), cfg.get("llm_api_key", "")


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
