"""Test execution tool (RunTestsTool). Wraps pytest + G33 exit code differentiation."""

from __future__ import annotations

import os
import subprocess

from ..base import Tool, ToolResult


class RunTestsTool(Tool):
    """Run project tests using the correct cwd and venv pytest.

    Structurally solves the problem of the model cd'ing to the wrong directory when
    running pytest via BashTool. Always executes from self.cwd and auto-discovers venv pytest.
    """

    name = "run_tests"
    description = (
        "Run project tests using the correct venv pytest from the project cwd. "
        "Automatically finds .venv/bin/pytest. Use this instead of bash for running pytest. "
        "Optionally specify a test path or extra pytest args."
    )

    def __init__(self, cwd: str = "."):
        self.cwd = cwd

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'Test path or file to run (e.g. "tests/apps/foo/test_bar.py"). Defaults to all tests.',
                },
                "pytest_path": {
                    "type": "string",
                    "description": "Absolute path to pytest executable. Auto-detected from .venv if omitted.",
                },
                "args": {
                    "type": "string",
                    "description": 'Extra pytest args (e.g. "-v --tb=short -x"). Default: "-v --tb=short".',
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120).",
                },
            },
            "required": [],
        }

    def execute(self, input: dict) -> ToolResult:
        from pathlib import Path

        test_path = input.get("path", "")
        extra_args = input.get("args", "-v --tb=short")
        timeout = input.get("timeout", 120)
        pytest_path = input.get("pytest_path", "")

        # Auto-discover venv pytest
        if not pytest_path:
            for root in [self.cwd] + [str(p) for p in Path(self.cwd).parents]:
                candidate = os.path.join(root, ".venv", "bin", "pytest")
                if os.path.exists(candidate):
                    pytest_path = candidate
                    break

        if not pytest_path:
            return ToolResult(content="pytest not found. Provide pytest_path or ensure .venv/bin/pytest exists.", is_error=True)

        # If a path was specified but does not exist, return a clear error immediately
        if test_path:
            abs_path = test_path if os.path.isabs(test_path) else os.path.join(self.cwd, test_path)
            if not os.path.exists(abs_path):
                return ToolResult(
                    content=f"✗ TEST PATH NOT FOUND: {test_path}\nThe path does not exist. Please create the file first or verify the path.",
                    is_error=True,
                )

        cmd = [pytest_path] + extra_args.split() + ([test_path] if test_path else [])

        # Clean up Python-related env vars — prevent hermit_agent venv contamination
        import copy
        env = copy.deepcopy(os.environ)
        for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONNOUSERSITE"):
            env.pop(key, None)

        try:
            result = subprocess.run(
                cmd,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            output = result.stdout + result.stderr
            content, is_error = self._format_pytest_output(result.returncode, output, test_path)
            return ToolResult(content=content, is_error=is_error)
        except subprocess.TimeoutExpired:
            return ToolResult(content=f"Timeout after {timeout}s", is_error=True)
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

    @staticmethod
    def _trim_pytest_output(output: str) -> str:
        """Extract only key information from pytest output (context optimization C1).

        Keep: FAILURES/ERRORS sections (tracebacks) + short test summary info + final summary line
        Remove: individual PASSED/FAILED lines (verbose), header/plugin info, xdist worker noise, warnings section
        """
        lines = output.splitlines()
        result: list[str] = []
        in_section = False   # Inside FAILURES/ERRORS/short test summary section
        in_warnings = False  # Inside warnings summary section (to be removed)

        for line in lines:
            # warnings section starts → target for removal
            if "= warnings summary =" in line.lower():
                in_warnings = True
                in_section = False
                continue
            # warnings section ends: next ===...=== separator
            if in_warnings:
                if line.startswith("=") and line.endswith("="):
                    in_warnings = False
                    # If this line starts FAILURES/ERRORS/short test summary, enter section
                    if "= FAILURES =" in line or "= ERRORS =" in line or "= short test summary info =" in line:
                        in_section = True
                        result.append(line)
                continue  # Discard all lines inside warnings section

            # Detect start of key section
            if "= FAILURES =" in line or "= ERRORS =" in line or "= short test summary info =" in line:
                in_section = True
                result.append(line)
                continue

            # Separator line ends the section
            if in_section and line.startswith("=") and line.endswith("=") and \
                    "short test summary" not in line and "FAILURES" not in line and "ERRORS" not in line:
                in_section = False
                result.append(line)  # Final summary line ("N failed, N passed in Xs")
                continue

            if in_section:
                result.append(line)

        trimmed = "\n".join(result).strip()
        # If no sections found at all, return only the last 10 lines
        if not trimmed:
            return "\n".join(lines[-10:]).strip()
        return trimmed

    @staticmethod
    def _format_pytest_output(returncode: int, output: str, test_path: str = "") -> tuple[str, bool]:
        """Generate a message for each pytest exit code (§34 G33).

        - 0: ✓ PASSED (summary line)
        - 1: ✗ TEST FAILED + traceback (trimmed)
        - 2: ✗ INTERRUPTED
        - 5: ⚠️ NO TESTS COLLECTED + hint
        - Other: ✗ pytest exit {code}
        """
        output = output or ""
        stripped = output.strip()
        last_lines = stripped.splitlines() if stripped else []
        summary_line = last_lines[-1] if last_lines else ""

        if returncode == 0:
            return (f"✓ PASSED\n{summary_line or 'passed'}", False)
        if returncode == 1:
            hint = (
                "✗ TEST FAILED\n\n"
                "If existing tests failed, distinguish two cases:\n"
                "1) Tests checking behavior I intentionally changed → update tests to match new behavior\n"
                "2) My code has a bug → fix the implementation\n"
                "In either case, make tests pass before declaring the task complete.\n\n"
            )
            trimmed = RunTestsTool._trim_pytest_output(output)
            return (hint + trimmed, True)
        if returncode == 2:
            body = RunTestsTool._trim_pytest_output(output) if output else "pytest was interrupted"
            return (f"✗ INTERRUPTED\n\n{body}", True)
        if returncode == 5:
            hint = (
                "⚠️ NO TESTS COLLECTED\n"
                "Check path/pattern — no test files found or collect rules did not match.\n"
            )
            if test_path:
                hint += f"path: {test_path}\n"
            if output:
                hint += f"\n{RunTestsTool._trim_pytest_output(output)}"
            return (hint, True)
        trimmed = RunTestsTool._trim_pytest_output(output) if output else ""
        return (f"✗ pytest exit {returncode}\n\n{trimmed}", True)


__all__ = ['RunTestsTool']
