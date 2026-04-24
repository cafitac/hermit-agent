"""Shell execution tool (BashTool)."""

from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from typing import Any

from ..base import Tool, ToolResult

_background_registry: dict[str, dict[str, Any]] = {}
# {process_id: {"proc": Popen, "stdout_path": str, "stderr_path": str, "command": str}}


class BashTool(Tool):
    name = "bash"
    description = "Execute a shell command and return stdout/stderr. Use for running tests, git commands, installing packages, etc. The shell starts in the project cwd. When running project tests, do NOT cd to a parent or different directory — use the absolute executable path (e.g. /path/to/.venv/bin/pytest) directly in the current cwd."

    DANGEROUS_PREFIXES = [
        "sudo ",
        "rm -rf /",
        "mkfs",
        "dd if=",
        "> /dev/",
        "chmod 777",
        "curl | sh",
        "wget | sh",
        "curl | bash",
        "wget | bash",
    ]

    READ_ONLY_PREFIXES = [
        "cat",
        "ls",
        "find",
        "grep",
        "rg",
        "head",
        "tail",
        "wc",
        "echo",
        "pwd",
        "which",
        "whoami",
        "date",
        "env",
        "git status",
        "git log",
        "git diff",
        "git branch",
        "python --version",
        "node --version",
    ]

    MAX_SUBCOMMANDS = 50

    def __init__(self, cwd: str = "."):
        self.cwd = cwd

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run command in background and return immediately with a process_id.",
                    "default": False,
                },
            },
            "required": ["command"],
        }

    def validate(self, input: dict) -> str | None:
        command = input.get("command", "")
        stripped = command.strip()
        self._last_command = command

        for prefix in self.DANGEROUS_PREFIXES:
            if stripped.startswith(prefix):
                return f"Blocked: command starts with dangerous prefix '{prefix}'"

        subcommands = re.split(r"&&|\|\||;|\|", command)
        if len(subcommands) > self.MAX_SUBCOMMANDS:
            return f"Blocked: command has {len(subcommands)} subcommands, exceeds limit of {self.MAX_SUBCOMMANDS}"

        return None

    def _is_read_only_command(self, command: str) -> bool:
        stripped = command.strip()
        return any(stripped.startswith(prefix) for prefix in self.READ_ONLY_PREFIXES)

    @property
    def is_read_only(self) -> bool:
        """True if the last validated command matches read-only patterns."""
        return self._is_read_only_command(getattr(self, "_last_command", ""))

    @staticmethod
    def classify_command(command: str) -> str:
        """Classify a shell command as 'read', 'write', or 'unknown'.

        For compound commands (&&, ||, ;, |), splits and classifies each
        subcommand individually. If ANY subcommand is 'write', the whole
        command is 'write'. (3.14 splitCommandWithOperators pattern)
        """
        subcommands = re.split(r'&&|\|\||;|\|', command)
        has_unknown = False
        for sub in subcommands:
            result = BashTool._classify_single(sub.strip())
            if result == "write":
                return "write"
            if result == "unknown":
                has_unknown = True
        return "unknown" if has_unknown else "read"

    @staticmethod
    def _classify_single(stripped: str) -> str:
        """Classify a single (non-compound) command."""
        if not stripped:
            return "read"
        if any(stripped.startswith(prefix) for prefix in BashTool.READ_ONLY_PREFIXES):
            return "read"
        write_indicators = [
            "git add", "git commit", "git push", "git checkout --",
            "rm ", "mv ", "cp ", "touch ", "mkdir ", "rmdir ",
            "pip install", "npm install", "yarn", "apt", "brew install",
            ">", ">>", "tee ", "sed -i", "awk ",
            "python ", "pytest", "make ", "cargo ",
        ]
        if any(stripped.startswith(ind) or ind in stripped for ind in write_indicators):
            return "write"
        return "unknown"

    def _execute_local(self, command: str, run_in_background: bool = False) -> ToolResult:
        """Execute command locally via subprocess in the current process."""
        if run_in_background:
            process_id = str(uuid.uuid4())[:8]
            stdout_f = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{process_id}.stdout", mode="w")
            stderr_f = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{process_id}.stderr", mode="w")
            background_proc: subprocess.Popen[Any] = subprocess.Popen(
                command, shell=True, executable="/bin/bash",
                stdout=stdout_f, stderr=stderr_f,
            )
            stdout_f.close()
            stderr_f.close()
            _background_registry[process_id] = {
                "proc": background_proc,
                "stdout_path": stdout_f.name,
                "stderr_path": stderr_f.name,
                "command": command,
                "stdout_offset": 0,
                "stderr_offset": 0,
            }
            return ToolResult(content=f"Background process started.\nProcess ID: {process_id}\nUse monitor tool with process_id to check status.")

        agent = getattr(self, "_agent", None)
        abort_event = getattr(agent, "abort_event", None) if agent else None

        try:
            proc: subprocess.Popen[str] = subprocess.Popen(
                command,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                start_new_session=True,
            )

            import time as _time
            deadline = _time.monotonic() + 120
            interrupted = False
            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if abort_event is not None and abort_event.is_set():
                        interrupted = True
                        break
                    if _time.monotonic() >= deadline:
                        proc.kill()
                        try:
                            proc.communicate(timeout=2)
                        except Exception:
                            pass
                        return ToolResult(content="Command timed out after 120s", is_error=True)

            if interrupted:
                try:
                    proc.terminate()
                    try:
                        proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.communicate(timeout=1)
                        except Exception:
                            pass
                except Exception:
                    pass
                return ToolResult(content="[Interrupted by user]", is_error=True)

            output = (stdout or "") + (stderr or "")
            return ToolResult(
                content=output[:10000] or "(no output)",
                is_error=proc.returncode != 0,
            )
        except Exception as e:
            return ToolResult(content=f"Error: {e}", is_error=True)

    def execute(self, input: dict) -> ToolResult:
        error = self.validate(input)
        if error:
            return ToolResult(content=error, is_error=True)

        command = input["command"]
        run_in_background = input.get("run_in_background", False)

        return self._execute_local(command, run_in_background=run_in_background)


__all__ = ['BashTool']
