"""Tests for `hermit_agent learner` CLI dispatch."""

import sys
from unittest.mock import patch

import pytest


class TestLearnerDispatch:
    """`hermit_agent learner` dispatch tests."""

    def test_status_delegates_to_agent_learner(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(
            "shutil.which",
            lambda x: "/usr/bin/agent-learner" if x == "agent-learner" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "status"])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        # subprocess.run should have been called with agent-learner
        assert any("agent-learner" in str(c) for c in calls)
        assert any("status" in str(c) for c in calls)

    def test_not_installed_prints_hint(self, monkeypatch, capsys):
        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "status"])

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "pip install agent-learner" in err

    def test_init_delegates(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "init"])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            from hermit_agent.__main__ import main
            main()

        assert any("init" in str(c) for c in calls)

    def test_invalid_subcommand_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "invalid-sub"])

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        assert exc_info.value.code == 1
        assert "Usage" in capsys.readouterr().err

    def test_dashboard_delegates(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "dashboard"])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            from hermit_agent.__main__ import main
            main()

        assert any("dashboard" in str(c) for c in calls)

    def test_process_delegates(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "process"])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            from hermit_agent.__main__ import main
            main()

        assert any("process" in str(c) for c in calls)

    def test_extra_args_forwarded(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "status", "--verbose", "--json"])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            from hermit_agent.__main__ import main
            main()

        last_cmd = calls[-1]
        assert "--verbose" in last_cmd
        assert "--json" in last_cmd

    def test_nonzero_exit_propagated(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: type("R", (), {"returncode": 42})(),
        )
        monkeypatch.setattr(sys, "argv", ["hermit_agent", "learner", "status"])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            from hermit_agent.__main__ import main
            main()

        assert exc_info.value.code == 42
