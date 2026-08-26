"""MCPB entry point; Claude Desktop installs Hermit through its UV runtime."""

import sys

from hermit_agent.config import init_settings_file
from hermit_agent.desktop_config import executor_config_error
from hermit_agent.mcp_launcher import main


if __name__ == "__main__":
    error = executor_config_error()
    if error:
        print(f"[hermit] {error}", file=sys.stderr)
        raise SystemExit(2)
    init_settings_file()
    main()
