from __future__ import annotations

import os
from unittest.mock import patch

from hermit_agent.hooks.runner import HookRunner, _normalize_hook_command, _validate_hooks_config_permissions
from hermit_agent.loop_commands._workflow import cmd_vim
from hermit_agent.tools.search.grep import GrepTool


def test_grep_fallback_uses_argv_without_shell(tmp_path):
    tool = GrepTool(cwd=str(tmp_path))

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            FileNotFoundError(),
            type("Result", (), {"stdout": "file.py:1:match\n"})(),
        ]

        result = tool.execute({"pattern": "a; rm -rf /", "path": str(tmp_path), "glob": "*.py"})

    assert result.is_error is False
    first_call = mock_run.call_args_list[0]
    second_call = mock_run.call_args_list[1]
    assert first_call.args[0][0] == "rg"
    assert second_call.args[0] == [
        "grep",
        "-rn",
        "--include",
        "*.py",
        "--",
        "a; rm -rf /",
        str(tmp_path),
    ]
    assert "shell" not in second_call.kwargs


def test_cmd_vim_uses_subprocess_without_shell(monkeypatch):
    class DummyAgent:
        pass

    monkeypatch.setenv("EDITOR", "vim -u NONE")
    with patch("subprocess.run") as mock_run:
        message = cmd_vim(DummyAgent(), "notes.txt; touch /tmp/pwned")

    assert message == "Opened notes.txt; touch /tmp/pwned in vim -u NONE"
    assert mock_run.call_args.args[0] == ["vim", "-u", "NONE", "notes.txt; touch /tmp/pwned"]
    assert mock_run.call_args.kwargs["check"] is False


def test_hook_runner_skips_insecure_config(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text('{"hooks":[{"event":"PreToolUse","tool":"bash","action":"deny"}]}', encoding="utf-8")
    os.chmod(hooks_path, 0o666)

    with patch("hermit_agent.hooks.runner.HOOKS_CONFIG", str(hooks_path)):
        runner = HookRunner()

    assert runner.hooks == []
    assert _validate_hooks_config_permissions(str(hooks_path)) == "Hooks config must not be group/world writable"


def test_create_default_hooks_config_writes_private_file(tmp_path):
    hooks_path = tmp_path / "hooks.json"

    with patch("hermit_agent.hooks.runner.HOOKS_CONFIG", str(hooks_path)):
        from hermit_agent.hooks.runner import create_default_hooks_config

        create_default_hooks_config()

    mode = hooks_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_hook_runner_uses_tokenized_command_without_shell(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        '{"hooks":[{"event":"PreToolUse","tool":"bash","command":"echo ok; touch /tmp/pwned"}]}',
        encoding="utf-8",
    )
    os.chmod(hooks_path, 0o600)

    with patch("hermit_agent.hooks.runner.HOOKS_CONFIG", str(hooks_path)), patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        runner = HookRunner()
        result = runner.run_hooks(event=runner.hooks[0].event, tool_name="bash", tool_input={"command": "ls"})

    assert result.action.value == "allow"
    assert mock_run.call_args.args[0] == ["echo", "ok;", "touch", "/tmp/pwned"]
    assert "shell" not in mock_run.call_args.kwargs


def test_hook_runner_accepts_argv_list_and_modified_input(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        '{"hooks":[{"event":"PreToolUse","tool":"bash","command":["hook-bin","--flag"]}]}',
        encoding="utf-8",
    )
    os.chmod(hooks_path, 0o600)

    with patch("hermit_agent.hooks.runner.HOOKS_CONFIG", str(hooks_path)), patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = '{"modified_input":{"command":"pwd"}}'
        mock_run.return_value.stderr = ""
        runner = HookRunner()
        result = runner.run_hooks(event=runner.hooks[0].event, tool_name="bash", tool_input={"command": "ls"})

    assert mock_run.call_args.args[0] == ["hook-bin", "--flag"]
    assert result.modified_input == {"command": "pwd"}


def test_normalize_hook_command_expands_env_and_rejects_empty():
    with patch.dict(os.environ, {"HOOK_BIN": "/tmp/hook-bin"}, clear=False):
        assert _normalize_hook_command("$HOOK_BIN --flag") == ["/tmp/hook-bin", "--flag"]

    try:
        _normalize_hook_command("   ")
    except ValueError as exc:
        assert "cannot be empty" in str(exc)
    else:
        raise AssertionError("Expected empty hook command to fail")
