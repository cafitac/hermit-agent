"""
GatewayPermissionChecker — moved MCPPermissionChecker into the Gateway package.
Same interface as mcp_server.py's MCPPermissionChecker.
"""
from __future__ import annotations

import os
import time

from ..codex_app_server_bridge import await_attached_codex_app_server_response
from ..channels_core.approvals import parse_permission_reply
from ..interactive_prompts import create_interactive_prompt


def _codex_method_for_tool(tool_name: str) -> str:
    if tool_name == "bash":
        return "item/commandExecution/requestApproval"
    if tool_name in {"edit_file", "write_file"}:
        return "item/fileChange/requestApproval"
    return "item/permissions/requestApproval"


def _codex_request_params(tool_name: str, arguments: dict, question: str) -> dict[str, object]:
    if tool_name == "bash":
        return {
            "command": str(arguments.get("command", "")),
            "reason": question,
        }
    return {"reason": question}


class GatewayPermissionChecker:
    """Permission checker for Gateway tasks.

    Puts permission requests into question_queue → ask_user_question → hermit-channel → CC session.
    When the user replies via reply_task in the CC session, execution is decided.

    Response rules:
      "y" / "yes" / "" → allow once
      "yolo" / "always" → auto-allow all subsequent requests
      Otherwise → deny
    """

    def __init__(self, mode, question_queue, reply_queue, notify_fn=None, notify_running_fn=None, permission_notify_fn=None, on_mode_change=None):
        self.mode = mode
        self._q_in = question_queue        # Queue for questions (→ hermit-channel)
        self._q_out = reply_queue          # Queue for replies (← CC reply_task)
        self._notify_fn = notify_fn        # SSE callback for ask_user_question waiting state
        self._notify_running_fn = notify_running_fn  # Running notification callback after consuming reply
        self._permission_notify_fn = permission_notify_fn or notify_fn  # SSE callback for bash permission_ask
        self.on_mode_change = on_mode_change  # Callback fired when mode flips to YOLO

    def check(self, tool_name: str, arguments: dict, is_read_only: bool) -> bool:
        from hermit_agent.permissions import PermissionMode, _tool_summary

        # In YOLO mode, allow without prompting
        # Also remove stale questions left by previous check() calls
        if self.mode == PermissionMode.YOLO:
            try:
                while True:
                    self._q_in.get_nowait()
            except Exception:
                pass
            return True

        # Read-only tools are always allowed
        if is_read_only:
            return True

        # ACCEPT_EDITS: allow file edits too, only ask for bash
        if self.mode == PermissionMode.ACCEPT_EDITS:
            if tool_name in ("edit_file", "write_file", "read_file"):
                return True
            # Classify bash command safety — auto-allow if safe
            if tool_name == "bash":
                from hermit_agent.permissions import classify_bash_safety
                if classify_bash_safety(arguments.get("command", "")) == "safe":
                    return True

        summary = _tool_summary(tool_name, arguments)
        question = (
            f"[Permission request] {tool_name}\n"
            f"{summary}\n\n"
            "Allow?"
        )
        options = ["Yes (once)", "Always allow (yolo)", "No"]

        attached_answer = await_attached_codex_app_server_response(
            create_interactive_prompt(
                task_id=f"permission-{tool_name}-{int(time.time() * 1000)}",
                question=question,
                options=options,
                prompt_kind="permission_ask",
                tool_name=tool_name,
                method=_codex_method_for_tool(tool_name),
                request_id=f"permission-{int(time.time() * 1000)}",
                params=_codex_request_params(tool_name, arguments, question),
            ),
            env=dict(os.environ),
        )
        if attached_answer is not None:
            if self._notify_running_fn:
                try:
                    self._notify_running_fn()
                except Exception:
                    pass
            decision = parse_permission_reply(attached_answer)
            if decision.escalate_to_yolo:
                self.mode = PermissionMode.YOLO
                if self.on_mode_change is not None:
                    self.on_mode_change(self.mode)
                return True
            return decision.allow

        try:
            self._q_in.put({"question": question, "options": options})
            # Emit permission_ask SSE (bash permission) — distinct from ask_user_question waiting
            _RENOTIFY_INTERVAL = 30   # Re-notify every 30s (prevent missed messages)
            _MAX_WAIT = 1800          # Max wait 30 minutes
            elapsed = 0
            answer = None
            method = _codex_method_for_tool(tool_name)
            if self._permission_notify_fn:
                try:
                    self._permission_notify_fn(question, options, tool_name=tool_name, method=method)
                except Exception:
                    pass
            while elapsed < _MAX_WAIT:
                try:
                    answer = self._q_out.get(timeout=_RENOTIFY_INTERVAL)
                    break
                except Exception:
                    elapsed += _RENOTIFY_INTERVAL
                    if elapsed < _MAX_WAIT and self._permission_notify_fn:
                        # Re-notify — the CC session may have missed the notification
                        try:
                            self._permission_notify_fn(question, options, tool_name=tool_name, method=method)
                        except Exception:
                            pass
            if answer is None:
                return False
            # Running notification right after consuming reply → stops server.ts retry loop immediately
            if self._notify_running_fn:
                try:
                    self._notify_running_fn()
                except Exception:
                    pass
        except Exception:
            return False

        decision = parse_permission_reply(answer)
        if decision.escalate_to_yolo:
            self.mode = PermissionMode.YOLO
            if self.on_mode_change is not None:
                self.on_mode_change(self.mode)
            return True
        return decision.allow
