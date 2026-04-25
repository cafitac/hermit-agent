from __future__ import annotations

import re

from .types import PermissionBehavior, PermissionMode, PermissionResult
from .utils import (
    _EDIT_TOOLS,
    _FS_TOOLS_GUARDED,
    _PATH_ARG_KEYS,
    _tool_summary,
    classify_bash_safety,
    is_sensitive_path,
)

import os


class PermissionChecker:
    def __init__(self, mode: PermissionMode = PermissionMode.ALLOW_READ):
        self.mode = mode

    def check_3step(self, tool_name: str, arguments: dict, is_read_only: bool) -> PermissionResult:
        """3-step decision (4.4): Tool.checkPermissions → hasPermissions → handler."""
        # Step 0 (safety floor): Block sensitive files in all modes including YOLO.
        if tool_name in _FS_TOOLS_GUARDED:
            for key in _PATH_ARG_KEYS:
                path = arguments.get(key)
                if path and is_sensitive_path(path):
                    return PermissionResult(
                        behavior=PermissionBehavior.DENY,
                        message=f"Blocked: sensitive file '{os.path.basename(path)}' (env/key/credentials)",
                    )

        # YOLO/DONT_ASK → Bypass permission check
        if self.mode in (PermissionMode.YOLO, PermissionMode.DONT_ASK):
            return self._check_mode(tool_name, arguments, is_read_only)

        # Split Bash compound commands and validate individually
        if tool_name == "bash":
            command = arguments.get("command", "")
            subcommands = re.split(r'&&|\|\||;|\|', command)
            for sub in subcommands:
                sub = sub.strip()
                if sub and classify_bash_safety(sub) == "unsafe":
                    return PermissionResult(
                        behavior=PermissionBehavior.DENY,
                        message=f"Blocked unsafe subcommand: {sub[:50]}",
                    )

        return self._check_mode(tool_name, arguments, is_read_only)

    def _check_mode(self, tool_name: str, arguments: dict, is_read_only: bool) -> PermissionResult:
        """Mode-based permission decision."""
        if self.mode == PermissionMode.YOLO:
            return PermissionResult(behavior=PermissionBehavior.ALLOW)
        if self.mode == PermissionMode.DONT_ASK:
            return PermissionResult(behavior=PermissionBehavior.ALLOW, message=f"[dont_ask] {tool_name}")
        if self.mode == PermissionMode.PLAN:
            if not is_read_only:
                return PermissionResult(behavior=PermissionBehavior.DENY, message=f"Plan mode: blocked {tool_name}")
            return PermissionResult(behavior=PermissionBehavior.ALLOW)
        if self.mode == PermissionMode.ACCEPT_EDITS:
            if is_read_only or tool_name in _EDIT_TOOLS:
                return PermissionResult(behavior=PermissionBehavior.ALLOW)
            if tool_name == "bash" and classify_bash_safety(arguments.get("command", "")) == "safe":
                return PermissionResult(behavior=PermissionBehavior.ALLOW)
            return PermissionResult(behavior=PermissionBehavior.ASK)
        if is_read_only:
            return PermissionResult(behavior=PermissionBehavior.ALLOW)
        return PermissionResult(behavior=PermissionBehavior.ASK)

    def check(self, tool_name: str, arguments: dict, is_read_only: bool) -> bool:
        """Permission check before tool execution. True to allow, False to deny."""
        result = self.check_3step(tool_name, arguments, is_read_only)
        if result.behavior == PermissionBehavior.ALLOW:
            if self.mode == PermissionMode.DONT_ASK:
                print(f"\033[2m{result.message}\033[0m")
            return True
        if result.behavior == PermissionBehavior.DENY:
            print(result.message)
            return False
        if result.behavior == PermissionBehavior.ASK:
            return self._prompt_user(tool_name, arguments)
        return self._prompt_user(tool_name, arguments)

    def _prompt_user(self, tool_name: str, arguments: dict) -> bool:
        YELLOW = "\033[33m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        summary = _tool_summary(tool_name, arguments)
        print(f"\n{YELLOW}{BOLD}Permission required:{RESET} {tool_name}")
        print(f"{DIM}  {summary}{RESET}")

        try:
            answer = input(f"{YELLOW}  Allow? [Y/n/yolo] {RESET}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return False

        if answer == "yolo":
            self.mode = PermissionMode.YOLO
            return True

        return answer in ("", "y", "yes")
