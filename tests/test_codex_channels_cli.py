"""Tests for `hermit_agent codex-channels` CLI dispatch."""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _make_install_report(tmp_path):
    """Build a minimal InstallCodexReport-like namespace."""
    return SimpleNamespace(
        install_command=["npm", "install"],
        install_mode="package",
        runtime_dir=str(tmp_path),
        settings_path=str(tmp_path / "settings.json"),
        serve_command=["node", "serve"],
        status_command=["node", "status"],
        marketplace_path=str(tmp_path / "marketplace"),
        state_file=str(tmp_path / "state.json"),
        plugin_path=str(tmp_path / "plugin.js"),
        package_spec="@cafitac/codex-channels@0.1.31",
        source_path=None,
    )


class TestCodexChannelsInstall:
    """`hermit_agent codex-channels install` dispatch tests."""

    def test_install_calls_install_fn(self, monkeypatch, tmp_path, capsys):
        report = _make_install_report(tmp_path)
        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.install_codex_channels",
            lambda **kw: report,
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "codex-channels", "install"])
        # Prevent codex-channels status/start/stop from running
        monkeypatch.setattr(sys, "exit", lambda code=0: None)

        from hermit_agent.__main__ import main
        main()

        out = capsys.readouterr().out
        assert "installed" in out
        assert "package" in out

    def test_install_failure_exits_1(self, monkeypatch, tmp_path, capsys):
        def _fail(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.install_codex_channels",
            _fail,
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "codex-channels", "install"])

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "boom" in err

    def test_install_passes_cwd(self, monkeypatch, tmp_path):
        captured_kwargs = {}

        def _capture_install(**kw):
            captured_kwargs.update(kw)
            return _make_install_report(tmp_path)

        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.install_codex_channels",
            _capture_install,
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "codex-channels", "install", "--cwd", str(tmp_path)])
        monkeypatch.setattr(sys, "exit", lambda code=0: None)

        from hermit_agent.__main__ import main
        main()

        assert captured_kwargs.get("cwd") == str(tmp_path)


class TestCodexChannelsUsage:
    """Usage / validation tests for codex-channels dispatch."""

    def test_invalid_subcommand_prints_usage(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "codex-channels", "bogus"])

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Usage" in err or "usage" in err.lower()

    def test_no_subcommand_prints_usage(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "codex-channels"])

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Usage" in err or "usage" in err.lower()
