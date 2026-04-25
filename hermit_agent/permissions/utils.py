from __future__ import annotations

import os
import re

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
    "python3 ~/.claude/hooks/", "python3 ~/.hermit/hooks/",
    "bash ~/.claude/scripts/", "bash ~/.hermit/scripts/",
    "bash ~/.claude/hooks/", "bash ~/.hermit/hooks/",
    # agent-learner learning CLI
    "agent-learner ",
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


def _expand_home(s: str) -> str:
    home = os.path.expanduser("~")
    return s.replace("~/", home + "/")


def _classify_single(command: str) -> str:
    """Single command safety classification."""
    expanded = _expand_home(command)
    if any(expanded.startswith(_expand_home(p)) for p in _SAFE_BASH_PREFIXES):
        return "safe"
    if any(p in command for p in _UNSAFE_BASH_PATTERNS):
        return "unsafe"
    return "unknown"


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
