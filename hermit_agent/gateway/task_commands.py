from __future__ import annotations


def _discover_available_models() -> list[dict[str, object]]:
    from ..config import load_settings, get_primary_model

    cfg = load_settings()

    models: list[dict[str, object]] = []
    default_model = get_primary_model(cfg, available_only=True) or get_primary_model(cfg)
    if default_model:
        models.append({"id": default_model, "source": "config", "default": True})

    try:
        import httpx

        r = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                name = m.get("name", "")
                if name and name != default_model:
                    models.append({"id": name, "source": "ollama", "default": False})
    except Exception:
        pass

    return models


def _handle_slash_command(text: str, *, discover_available_models=None) -> str | None:
    """Slash commands that the gateway can handle immediately."""
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    cmd_args = parts[1].strip() if len(parts) > 1 else ""
    discover_models = discover_available_models or _discover_available_models

    if cmd == "/help":
        try:
            from ..loop import SLASH_COMMANDS

            lines = ["Available commands:"]
            for name, info in sorted(SLASH_COMMANDS.items()):
                lines.append(f"  /{name:12s} {info['description']}")
            return "\n".join(lines)
        except Exception:
            return "Could not load command list."

    if cmd == "/model":
        if cmd_args:
            return f"Model changed to {cmd_args}. (Applied from next run)"
        lines = ["Available models:"]
        for model in discover_models():
            suffix = " (default)" if model["default"] else ""
            lines.append(f"  {model['id']}{suffix} [{model['source']}]")
        if len(lines) == 1:
            lines.append("  (No models)")
        return "\n".join(lines)

    if cmd == "/status":
        return "Gateway mode — /status is not yet supported."

    if cmd == "/resume":
        return "Gateway mode does not support /resume."

    return None
