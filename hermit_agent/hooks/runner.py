from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from stat import S_IWGRP, S_IWOTH
from typing import Callable

from .types import HOOKS_CONFIG, HookAction, HookDefinition, HookEvent, HookResult


class HookRunner:
    """Hook runner."""

    def __init__(self):
        self.hooks: list[HookDefinition] = []
        self._python_hooks: list[tuple[HookEvent, str, Callable]] = []
        self._load_config()

    def _load_config(self):
        """Load hooks from config file."""
        if not os.path.exists(HOOKS_CONFIG):
            return

        try:
            error = _validate_hooks_config_permissions(HOOKS_CONFIG)
            if error:
                return
            with open(HOOKS_CONFIG) as f:
                config = json.load(f)

            for h in config.get("hooks", []):
                self.hooks.append(HookDefinition(
                    event=HookEvent(h["event"]),
                    tool=h.get("tool", "*"),
                    condition=h.get("if"),
                    command=h.get("command"),
                    action=HookAction(h.get("action", "allow")),
                    message=h.get("message", ""),
                ))
        except Exception:
            pass  # Ignore config file parse failures

    def register(self, event: HookEvent, tool: str, callback: Callable):
        """Register a Python function as a hook."""
        self._python_hooks.append((event, tool, callback))

    def run_hooks(
        self,
        event: HookEvent,
        tool_name: str,
        tool_input: dict,
        tool_output: str | None = None,
    ) -> HookResult:
        """Execute matching hooks in order. Stop at first deny."""

        # Config file hooks
        for hook in self.hooks:
            if hook.event != event:
                continue
            if hook.tool != "*" and hook.tool != tool_name:
                continue

            # Condition check
            if hook.condition:
                input_str = json.dumps(tool_input)
                if hook.condition not in input_str:
                    continue

            # Shell command execution
            if hook.command:
                env = {
                    **os.environ,
                    "HERMIT_TOOL": tool_name,
                    "HERMIT_INPUT": json.dumps(tool_input),
                    "HERMIT_EVENT": event.value,
                }
                if tool_output:
                    env["HERMIT_OUTPUT"] = tool_output[:5000]

                try:
                    argv = _normalize_hook_command(hook.command)
                    result = subprocess.run(
                        argv,
                        capture_output=True,
                        text=True, timeout=10, env=env,
                    )
                    if result.returncode != 0:
                        return HookResult(
                            action=HookAction.DENY,
                            message=hook.message or result.stderr.strip() or "Hook denied",
                        )
                    stdout = result.stdout.strip()
                    if stdout:
                        try:
                            hook_output = json.loads(stdout)
                            if "modified_input" in hook_output:
                                return HookResult(action=HookAction.MODIFY, modified_input=hook_output["modified_input"])
                        except json.JSONDecodeError:
                            pass  # Not JSON, treat as regular allow message
                except Exception as e:
                    return HookResult(action=HookAction.DENY, message=f"Hook error: {e}")

            # Explicit deny/allow
            if hook.action == HookAction.DENY:
                return HookResult(action=HookAction.DENY, message=hook.message)

        # Python hooks
        for h_event, h_tool, callback in self._python_hooks:
            if h_event != event:
                continue
            if h_tool != "*" and h_tool != tool_name:
                continue

            try:
                result = callback(tool_name, tool_input, tool_output)
                if isinstance(result, HookResult):
                    if result.action == HookAction.DENY:
                        return result
            except Exception:
                pass

        return HookResult(action=HookAction.ALLOW)


def create_default_hooks_config():
    """Create default hooks config file if it doesn't exist."""
    if os.path.exists(HOOKS_CONFIG):
        return

    os.makedirs(os.path.dirname(HOOKS_CONFIG), exist_ok=True)
    default = {
        "hooks": [
            {
                "event": "PreToolUse",
                "tool": "bash",
                "if": "rm -rf /",
                "action": "deny",
                "message": "Blocked: dangerous rm -rf / command",
            },
        ],
    }
    fd = os.open(HOOKS_CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(default, f, indent=2)


def _validate_hooks_config_permissions(path: str) -> str | None:
    config_path = Path(path)
    try:
        stat_result = config_path.stat()
    except OSError as exc:
        return f"Unable to stat hooks config: {exc}"

    if not config_path.is_file():
        return "Hooks config must be a regular file"

    if stat_result.st_uid != os.getuid():
        return "Hooks config must be owned by the current user"

    if stat_result.st_mode & (S_IWGRP | S_IWOTH):
        return "Hooks config must not be group/world writable"

    return None


def _normalize_hook_command(command: str | list[str]) -> list[str]:
    if isinstance(command, str):
        argv = shlex.split(command)
    elif isinstance(command, list) and all(isinstance(part, str) for part in command):
        argv = command
    else:
        raise TypeError("Hook command must be a string or list of strings")

    if not argv:
        raise ValueError("Hook command cannot be empty")

    return [os.path.expandvars(os.path.expanduser(part)) for part in argv]
