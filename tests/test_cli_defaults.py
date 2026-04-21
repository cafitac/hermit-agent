"""Tests for CLI argument defaults in hermit_agent.__main__."""
from hermit_agent.__main__ import _resolve_api_key, _resolve_model, parse_args


class TestDefaultBaseUrl:
    def test_default_base_url_is_gateway(self):
        """--base-url default must point to the local Hermit gateway, not Ollama."""
        ns = parse_args([])
        assert ns.base_url == "http://localhost:8765/v1"

    def test_custom_base_url_overrides_default(self):
        ns = parse_args(["--base-url", "http://x"])
        assert ns.base_url == "http://x"


class TestDefaultApiKey:
    """--api-key falls through: CLI flag > HERMIT_API_KEY env > settings.json::gateway_api_key."""

    def test_cli_flag_wins(self, monkeypatch):
        monkeypatch.setenv("HERMIT_API_KEY", "env-tok")
        ns = parse_args(["--api-key", "cli-tok"])
        assert _resolve_api_key(ns) == "cli-tok"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("HERMIT_API_KEY", "env-tok")
        ns = parse_args([])
        assert _resolve_api_key(ns) == "env-tok"

    def test_none_when_env_and_settings_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HERMIT_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", tmp_path / "nope.json")
        ns = parse_args([])
        assert _resolve_api_key(ns) is None


class TestDefaultModel:
    def test_cli_flag_wins(self):
        ns = parse_args(["--model", "custom-model"])
        assert _resolve_model(ns) == "custom-model"

    def test_fallback_to_hardcoded_default_when_settings_empty(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", tmp_path / "nope.json")
        ns = parse_args([])
        assert _resolve_model(ns) == "qwen3-coder:30b"


def test_main_dispatches_install_codex(monkeypatch, capsys):
    from hermit_agent import __main__ as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["hermit-agent", "install-codex", "--cwd", "/tmp/demo"])
    monkeypatch.setattr("hermit_agent.install_codex.run_install_codex", lambda **kwargs: f"installed:{kwargs['cwd']}")

    main_mod.main()

    assert "installed:/tmp/demo" in capsys.readouterr().out
