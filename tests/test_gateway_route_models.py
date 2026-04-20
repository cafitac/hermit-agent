from __future__ import annotations


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_discover_available_models_combines_config_and_ollama(monkeypatch):
    from hermit_agent.gateway.routes import tasks as tasks_mod

    monkeypatch.setattr("hermit_agent.config.load_settings", lambda: {"x": 1})

    def fake_get_primary_model(cfg, available_only=False):
        return "glm-5.1" if available_only else "glm-5.0"

    monkeypatch.setattr("hermit_agent.config.get_primary_model", fake_get_primary_model)
    monkeypatch.setattr(
        "httpx.get",
        lambda *args, **kwargs: _FakeResponse(
            200,
            {"models": [{"name": "glm-5.1"}, {"name": "codex-mini"}, {"name": ""}]},
        ),
    )

    assert tasks_mod._discover_available_models() == [
        {"id": "glm-5.1", "source": "config", "default": True},
        {"id": "codex-mini", "source": "ollama", "default": False},
    ]


def test_model_slash_command_uses_discovered_models(monkeypatch):
    from hermit_agent.gateway.routes import tasks as tasks_mod

    monkeypatch.setattr(
        tasks_mod,
        "_discover_available_models",
        lambda: [
            {"id": "glm-5.1", "source": "config", "default": True},
            {"id": "codex-mini", "source": "ollama", "default": False},
        ],
    )

    result = tasks_mod._handle_slash_command("/model")

    assert result == "\n".join(
        [
            "Available models:",
            "  glm-5.1 (default) [config]",
            "  codex-mini [ollama]",
        ]
    )


def test_model_slash_command_shows_empty_state(monkeypatch):
    from hermit_agent.gateway.routes import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "_discover_available_models", lambda: [])

    assert tasks_mod._handle_slash_command("/model") == "Available models:\n  (No models)"
