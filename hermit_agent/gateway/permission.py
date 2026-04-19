from __future__ import annotations
"""
GatewayPermissionChecker — moved MCPPermissionChecker into the Gateway package.
Same interface as mcp_server.py's MCPPermissionChecker.
"""


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
        from hermit_agent.permissions import PermissionMode
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

        try:
            self._q_in.put({"question": question, "options": options})
            # Emit permission_ask SSE (bash permission) — distinct from ask_user_question waiting
            _RENOTIFY_INTERVAL = 30   # Re-notify every 30s (prevent missed messages)
            _MAX_WAIT = 1800          # Max wait 30 minutes
            elapsed = 0
            answer = None
            if self._permission_notify_fn:
                try:
                    self._permission_notify_fn(question, options)
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
                            self._permission_notify_fn(question, options)
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

        answer = answer.strip().lower()
        if 'yolo' in answer or 'always' in answer or answer == '2':
            self.mode = PermissionMode.YOLO
            if self.on_mode_change is not None:
                self.on_mode_change(self.mode)
            return True
        if answer == 'no' or answer.startswith('no'):
            return False
        return answer in ('', 'y', 'yes', '1') or 'yes' in answer or 'once' in answer
