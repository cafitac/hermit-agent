"""File content search tool (GrepTool)."""

from __future__ import annotations

import subprocess

from ..base import Tool, ToolResult, _expand_path


class GrepTool(Tool):
    name = "grep"
    description = "Search file contents using ripgrep. Returns matching lines with file paths and line numbers."
    is_read_only = True
    is_concurrent_safe = True

    def __init__(self, cwd: str = "."):
        self.cwd = cwd

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in (default: current directory)",
                },
                "glob": {
                    "type": "string",
                    "description": 'File pattern filter (e.g. "*.py")',
                },
                "max_count": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 50)",
                    "default": 50,
                },
            },
            "required": ["pattern"],
        }

    def execute(self, input: dict) -> ToolResult:
        pattern = input["pattern"]
        search_path = _expand_path(input.get("path", self.cwd), self.cwd)
        file_glob = input.get("glob")
        max_count = input.get("max_count", 50)

        cmd = ["rg", "--no-heading", "--line-number", "--max-count", str(max_count), pattern, search_path]
        if file_glob:
            cmd.extend(["--glob", file_glob])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout
            if not output:
                return ToolResult(content=f"No matches for pattern: {pattern}")
            return ToolResult(content=output[:10000])
        except FileNotFoundError:
            # Fall back to grep if ripgrep is not available
            grep_cmd: list[str] = ["grep", "-rn"]
            if file_glob:
                grep_cmd.extend(["--include", file_glob])
            grep_cmd.extend(["--", pattern, search_path])
            try:
                result = subprocess.run(grep_cmd, capture_output=True, text=True, timeout=30)
                output = result.stdout
                if not output:
                    return ToolResult(content=f"No matches for pattern: {pattern}")
                return ToolResult(content=output[:10000])
            except Exception as e:
                return ToolResult(content=f"Error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Error: {e}", is_error=True)


__all__ = ['GrepTool']
