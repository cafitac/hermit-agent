"""Permission system — Refer to Claude Code's PermissionMode/PermissionResult pattern.

6 modes:
- ask: Prompt user when using write tools (default)
- allow_read: Auto-allow read tools, prompt only for write
- accept_edits: Auto-allow read+edit, prompt only for bash
- yolo: Auto-allow all tools (dangerous)
- dont_ask: Auto-allow all tools + log output
- plan: Read-only, block write operations
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum


class PermissionBehavior(Enum):
    """4 permission behaviors. Claude Code's PermissionResult pattern."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    PASSTHROUGH = "passthrough"  # Delegate to the general permission system


@dataclass
class PermissionResult:
    """3-step decision result."""
    behavior: PermissionBehavior
    message: str = ""
    updated_input: dict | None = None


_EDIT_TOOLS = ("edit_file", "write_file")

_SAFE_BASH_PREFIXES = [
    "ls", "cat", "head", "tail", "wc", "echo", "pwd", "which",
    "whoami", "date", "env", "grep", "rg", "find", "tree", "file", "stat",
    # git read commands
    "git status", "git log", "git diff", "git branch", "git show",
    "git remote", "git tag", "git stash list", "git rev-parse",
    "git -C", "git --git-dir",
    # git write commands (safe in development workflows)
    "git fetch", "git pull", "git push", "git add", "git commit",
    "git checkout", "git switch", "git merge", "git rebase",
    "git reset", "git stash", "git restore", "git cherry-pick",
    "git worktree",
    # Development tools
    "python --version", "python3 --version", "node --version",
    "python3 ~/.claude/scripts/", "python3 ~/.hermit/scripts/",
    "bash ~/.claude/scripts/", "bash ~/.hermit/scripts/",
    "source ~/.zshrc", "pytest", "ruff", "mypy",
    # Change directory (standalone cd, not compound)
    "cd ",
    # jira CLI
    "jira ",
    # gh CLI (read)
    "gh pr view", "gh pr list", "gh issue view", "gh issue list",
    # gh CLI (write — PR update/creation is a development workflow)
    "gh pr edit", "gh pr create", "gh pr comment",
]

_UNSAFE_BASH_PATTERNS = [
    "rm -rf", "sudo", "mkfs", "dd if=", "> /dev/", "chmod 777",
    "curl | sh", "wget | sh", ":(){ :",
]

_SENSITIVE_BASENAME_PATTERNS = [
    r"^\.env(\..+)?$",
    r".+\.pem$",
    r".+\.key$",
    r"^credentials.*",
    r"^secrets.*",
    r"^id_(rsa|ed25519|ecdsa|dsa)$",
]
_SENSITIVE_RE = [re.compile(p, re.IGNORECASE) for p in _SENSITIVE_BASENAME_PATTERNS]

_SENSITIVE_ALLOWLIST = {".env.example", ".env.sample"}

_FS_TOOLS_GUARDED = ("read_file", "write_file", "edit_file")
_PATH_ARG_KEYS = ("path", "file_path")


def is_sensitive_path(path: str) -> bool:
    """Determine if a file is sensitive based on its basename. The floor that should be blocked even in YOLO mode."""
    basename = os.path.basename(path.rstrip("/"))
    if basename in _SENSITIVE_ALLOWLIST:
        return False
    return any(r.match(basename) for r in _SENSITIVE_RE)


def classify_bash_safety(command: str) -> str:
    """Classify bash command safety: 'safe', 'unsafe', or 'unknown'.

    compound command(cd && git ...) processing:
    - If all subcommands are 'safe' → 'safe'
    - If any is 'unsafe' → 'unsafe'
    - Otherwise → 'unknown'
    """
    stripped = command.strip()

    # Split compound commands
    subcommands = re.split(r'&&|\|\||;', stripped)
    if len(subcommands) > 1:
        results = [_classify_single(s.strip()) for s in subcommands if s.strip()]
        if any(r == "unsafe" for r in results):
            return "unsafe"
        if all(r == "safe" for r in results):
            return "safe"
        return "unknown"

    return _classify_single(stripped)


def _classify_single(command: str) -> str:
    """Single command safety classification."""
    if _has_unsafe_shell_features(command):
        return "unsafe"
    if any(p in command for p in _UNSAFE_BASH_PATTERNS):
        return "unsafe"
    if any(command.startswith(p) for p in _SAFE_BASH_PREFIXES):
        return "safe"
    return "unknown"


def _has_unsafe_shell_features(command: str) -> bool:
    return "$(" in command or "`" in command


class PermissionMode(Enum):
    ASK = "ask"
    ALLOW_READ = "allow_read"
    ACCEPT_EDITS = "accept_edits"
    YOLO = "yolo"
    DONT_ASK = "dont_ask"
    PLAN = "plan"


class PermissionChecker:
    def __init__(self, mode: PermissionMode = PermissionMode.ALLOW_READ):
        self.mode = mode

    def check_3step(self, tool_name: str, arguments: dict, is_read_only: bool) -> PermissionResult:
        """3-step decision (4.4): Tool.checkPermissions → hasPermissions → handler.

        Step 1: Tool's own permission check (is_read_only, etc.)
        Step 2: Mode-based decision (yolo/plan/accept_edits, etc.)
        Step 3: User prompt (ask)
        """
        # Step 0 (safety floor): Block sensitive files in all modes. Including YOLO.
        if tool_name in _FS_TOOLS_GUARDED:
            for key in _PATH_ARG_KEYS:
                path = arguments.get(key)
                if path and is_sensitive_path(path):
                    return PermissionResult(
                        behavior=PermissionBehavior.DENY,
                        message=f"Blocked: sensitive file '{os.path.basename(path)}' (env/key/credentials)",
                    )

        # YOLO/DONT_ASK → Bypass permission check (the tool's own validate() blocks dangerous commands)
        if self.mode in (PermissionMode.YOLO, PermissionMode.DONT_ASK):
            return self._check_mode(tool_name, arguments, is_read_only)

        # 4.10: Split Bash compound commands and validate individually (additionally block dangerous commands in ask/plan/accept_edits modes)
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

        result = self._check_mode(tool_name, arguments, is_read_only)
        return result

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
        """Permission check before tool execution. True to allow, False to deny. (Compatibility interface)"""
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
        # PASSTHROUGH → ask
        return self._prompt_user(tool_name, arguments)

    def _prompt_user(self, tool_name: str, arguments: dict) -> bool:
        YELLOW = "\033[33m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        # Display summary by tool
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


def _tool_summary(tool_name: str, arguments: dict) -> str:
    if tool_name == "bash":
        return arguments.get("command", "")[:100]
    elif tool_name == "write_file":
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        return f"{path} ({len(content)} chars)"
    elif tool_name == "edit_file":
        return arguments.get("path", "")
    else:
        return str(arguments)[:100]
