"""
GatewayPermissionChecker — moved MCPPermissionChecker into the Gateway package.
Same interface as mcp_server.py's MCPPermissionChecker.
"""
from __future__ import annotations

def _permission_reply(answer: object) -> tuple[bool, bool]:
    """Return (allow, always_allow) for the portable reply_task protocol."""
    normalized = str(answer or "").strip().casefold()
    always_allow = normalized in {"always", "yolo", "2", "always allow (yolo)"}
    allow = always_allow or normalized in {"", "y", "yes", "1", "yes (once)", "allow"}
    return allow, always_allow


class GatewayPermissionChecker:
    """Permission checker for Gateway tasks.

    Puts permission requests into the task queue. Every host responds through
    the public reply_task MCP tool; no host-specific channel is involved.

    Response rules:
      "y" / "yes" / "" → allow once
      "yolo" / "always" → auto-allow all subsequent requests
      Otherwise → deny
    """

    def __init__(self, mode, question_queue, reply_queue, notify_fn=None, notify_running_fn=None, permission_notify_fn=None, on_mode_change=None):
        self.mode = mode
        self._q_in = question_queue
        self._q_out = reply_queue
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

        try:
            self._q_in.put({"question": question, "options": options})
            # Emit permission_ask SSE (bash permission) — distinct from ask_user_question waiting
            _RENOTIFY_INTERVAL = 30   # Re-notify every 30s (prevent missed messages)
            _MAX_WAIT = 1800          # Max wait 30 minutes
            elapsed = 0
            answer = None
            if self._permission_notify_fn:
                try:
                    self._permission_notify_fn(question, options, tool_name=tool_name)
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
                            self._permission_notify_fn(question, options, tool_name=tool_name)
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

        allowed, always_allow = _permission_reply(answer)
        if always_allow:
            self.mode = PermissionMode.YOLO
            if self.on_mode_change is not None:
                self.on_mode_change(self.mode)
        return allowed
