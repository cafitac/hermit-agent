import os
import pytest

# Redirect MCP server log to /dev/null during tests so pytest runs
# don't pollute ~/.hermit/mcp_server.log with FakeSession entries.
os.environ.setdefault("HERMIT_LOG_PATH", os.devnull)
