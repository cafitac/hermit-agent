"""Tests for `hermit codex-channels` CLI subcommands."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 4317
    state_file: str = ""
    runtime_dir: str = ""


def _run_cli(*extra_args: str) -> subprocess.CompletedProcess[str]:
    """Run hermit_agent codex-channels ... and return CompletedProcess."""
    venv_python = os.environ.get("HERMIT_VENV_PYTHON", sys.executable)
    return subprocess.run(
        [venv_python, "-m", "hermit_agent", "codex-channels", *extra_args],
        capture_output=True,
        text=True,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCodexChannelsStatusCLI:
    """Test `hermit codex-channels status` CLI subcommand."""

    def test_status_prints_unreachable_when_server_down(self, monkeypatch, tmp_path):
        """When health check fails, status should print 'unreachable' and exit non-zero."""
        from hermit_agent.__main__ import _run_codex_channels_status

        def _raise(*a, **kw):
            raise OSError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.load_codex_channels_settings",
            lambda cfg, cwd: _FakeSettings(enabled=True),
        )
        monkeypatch.setattr(
            "hermit_agent.config.load_settings",
            lambda cwd={}: {},
        )

        # Capture SystemExit
        with pytest.raises(SystemExit) as exc_info:
            _run_codex_channels_status(cwd=str(tmp_path))
        assert exc_info.value.code == 1

    def test_status_prints_reachable_when_server_up(self, monkeypatch, tmp_path, capsys):
        """When health check returns 200, status should print 'reachable' and exit 0."""
        from hermit_agent.__main__ import _run_codex_channels_status

        class MockResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: MockResp())
        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.load_codex_channels_settings",
            lambda cfg, cwd: _FakeSettings(enabled=True),
        )
        monkeypatch.setattr(
            "hermit_agent.config.load_settings",
            lambda cwd={}: {},
        )

        _run_codex_channels_status(cwd=str(tmp_path))
        captured = capsys.readouterr()
        assert "reachable" in captured.out


class TestCodexChannelsStartCLI:
    """Test `hermit codex-channels start` CLI subcommand."""

    def test_start_launches_serve_command(self, monkeypatch, tmp_path):
        from hermit_agent.__main__ import _run_codex_channels_start

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None

        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **kw: mock_proc
        )
        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.load_codex_channels_settings",
            lambda cfg, cwd: _FakeSettings(enabled=True, runtime_dir=str(tmp_path)),
        )
        monkeypatch.setattr(
            "hermit_agent.config.load_settings",
            lambda cwd={}: {},
        )
        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.build_runtime_serve_command",
            lambda *, settings: ["echo", "serve"],
        )

        _run_codex_channels_start(cwd=str(tmp_path))
        # Verify PID file was written
        pid_file = tmp_path / "codex-channels.pid"
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "12345"


class TestCodexChannelsStopCLI:
    """Test `hermit codex-channels stop` CLI subcommand."""

    def test_stop_kills_process_from_pid_file(self, monkeypatch, tmp_path):
        from hermit_agent.__main__ import _run_codex_channels_stop

        pid_file = tmp_path / "codex-channels.pid"
        pid_file.write_text("99999")

        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.load_codex_channels_settings",
            lambda cfg, cwd: _FakeSettings(enabled=True, runtime_dir=str(tmp_path)),
        )
        monkeypatch.setattr(
            "hermit_agent.config.load_settings",
            lambda cwd={}: {},
        )

        killed_pid = {}

        def mock_kill(pid, sig):
            killed_pid["pid"] = pid
            killed_pid["sig"] = sig

        monkeypatch.setattr(os, "kill", mock_kill)

        _run_codex_channels_stop(cwd=str(tmp_path))
        assert killed_pid == {"pid": 99999, "sig": signal.SIGTERM}
        assert not pid_file.exists()

    def test_stop_succeeds_when_no_pid_file(self, monkeypatch, tmp_path, capsys):
        from hermit_agent.__main__ import _run_codex_channels_stop

        monkeypatch.setattr(
            "hermit_agent.codex.channels_adapter.load_codex_channels_settings",
            lambda cfg, cwd: _FakeSettings(enabled=True, runtime_dir=str(tmp_path)),
        )
        monkeypatch.setattr(
            "hermit_agent.config.load_settings",
            lambda cwd={}: {},
        )

        _run_codex_channels_stop(cwd=str(tmp_path))
        captured = capsys.readouterr()
        assert "not running" in captured.out.lower()
