from __future__ import annotations

from unittest.mock import MagicMock

from hermit_agent.executor_readiness import inspect_executor_readiness


def test_readiness_reports_missing_openai_compatible_configuration_without_secret() -> None:
    readiness = inspect_executor_readiness(
        {
            "providers": {"budget": {"base_url": "https://llm.example.com/v1", "api_key_env": "BUDGET_KEY"}},
            "routing": {"priority_models": [{"model": "coder-small", "provider": "budget"}]},
        }
    )

    assert readiness.status == "needs-configuration"
    assert "BUDGET_KEY" in "\n".join(readiness.routes)
    assert "secret" not in "\n".join(readiness.routes).lower()


def test_readiness_accepts_openai_compatible_environment_secret(monkeypatch) -> None:
    monkeypatch.setenv("BUDGET_KEY", "not-displayed")

    readiness = inspect_executor_readiness(
        {
            "providers": {"budget": {"base_url": "https://llm.example.com/v1", "api_key_env": "BUDGET_KEY"}},
            "routing": {"priority_models": [{"model": "coder-small", "provider": "budget"}]},
        }
    )

    assert readiness.ready
    assert "not-displayed" not in "\n".join(readiness.routes)


def test_readiness_reports_missing_ollama_model(monkeypatch) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"models": [{"name": "qwen3-coder:7b"}]}
    monkeypatch.setattr("hermit_agent.executor_readiness.httpx.get", lambda *args, **kwargs: response)

    readiness = inspect_executor_readiness(
        {"ollama_url": "http://localhost:11434/v1", "routing": {"priority_models": [{"model": "qwen3-coder:30b"}]}}
    )

    assert readiness.status == "needs-configuration"
    assert "ollama pull qwen3-coder:30b" in "\n".join(readiness.guidance)


def test_readiness_distinguishes_an_unavailable_ollama_service(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("hermit_agent.executor_readiness.httpx.get", unavailable)

    readiness = inspect_executor_readiness(
        {"ollama_url": "http://localhost:11434/v1", "routing": {"priority_models": [{"model": "qwen3-coder:30b"}]}}
    )

    assert readiness.status == "needs-configuration"
    assert "Ollama unavailable" in "\n".join(readiness.routes)
    assert "Start Ollama" in "\n".join(readiness.guidance)


def test_readiness_accepts_installed_ollama_model(monkeypatch) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"models": [{"name": "qwen3-coder:30b:latest"}]}
    monkeypatch.setattr("hermit_agent.executor_readiness.httpx.get", lambda *args, **kwargs: response)

    readiness = inspect_executor_readiness(
        {"ollama_url": "http://localhost:11434/v1", "routing": {"priority_models": [{"model": "qwen3-coder:30b"}]}}
    )

    assert readiness.ready
