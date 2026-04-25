from __future__ import annotations

import json
import os
import subprocess
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
                    result = subprocess.run(
                        hook.command, shell=True, capture_output=True,
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
    with open(HOOKS_CONFIG, "w") as f:
        json.dump(default, f, indent=2)
