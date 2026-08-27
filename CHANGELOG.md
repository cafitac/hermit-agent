# Changelog

## v0.4.3

### Safe diagnosis and tokenless publishing

- Added `hermit doctor --json`, a stable paste-safe readiness report that keeps
  Claude Code, Codex, gateway, and executor diagnostics separate while
  redacting credentials from both JSON and human-readable output.
- Added a dedicated maintainer host-acceptance checklist and a safe GitHub
  issue-reporting path for installation diagnostics.
- Updated release artifact actions and changed PyPI publishing to GitHub OIDC
  Trusted Publishing. The legacy PyPI token remains available only until the
  first successful OIDC release is independently verified.

## v0.4.2

### First-task reliability

- `run_task` now checks executor readiness before it creates a background task.
  Missing OpenAI-compatible configuration, an unavailable Ollama service, or a
  missing Ollama model returns the same actionable diagnosis shown by
  `hermit doctor` and `hermit install`.
- Clarified the README's Claude Code, Codex, and Claude Desktop first-task
  flow, including the cost-optimization role and safe recovery path.
- Switched npm publishing to GitHub Actions Trusted Publishing with OIDC; the
  release workflow no longer reads an npm token.

## v0.4.1

### First-run readiness

- Added executor readiness to `hermit doctor` and `hermit install`: host MCP
  registration, gateway health, and a usable Ollama or OpenAI-compatible route
  are reported separately.
- Added `hermit configure` for OpenAI-compatible endpoints. It stores only an
  API-key environment-variable name, never the API key itself.
- The local gateway now binds to loopback by default. If its preferred port is
  occupied by another process, Hermit leaves that process untouched and safely
  moves to an available loopback port.
- Corrected the README: target-specific install commands register only their
  selected host; bare `hermit install` registers both.

## v0.4.0

### Breaking changes

- Removed the standalone React/Ink terminal UI and its private interactive
  session/bridge runtime.
- Removed host-specific notification channels from the MCP runtime. Hosts use
  `check_task` polling and `reply_task` for every task state transition.
- Replaced the large standalone-agent CLI with `hermit install`,
  `hermit doctor`, and `hermit mcp-server`.
- Reduced the CLI surface to MCP installation and runtime commands.

### Installation

- `hermit install claude` registers `hermit` in Claude Code.
- `hermit install codex` registers `hermit` through the Codex CLI.
- `hermit install` registers both hosts.
- The matching GitHub Release includes a Claude Desktop `.mcpb` extension for
  macOS and Windows. It uses the UV runtime instead of a user-installed Python.

The stable configured command remains `hermit mcp-server`.
