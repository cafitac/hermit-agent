# Changelog

## Unreleased

## v0.3.10

### TUI interactive session runtime and codebase hygiene
- Reworked the standalone TUI to use a gateway-private interactive session runtime so multi-turn continuity survives across normal turns without widening the public MCP task APIs.
- Added private interactive session routes, transcript persistence in `mode='interactive'`, explicit `/resume`-driven recovery, and recap/lineage alignment around the interactive runtime.
- Removed the dormant `BridgeAgentSession` / bridge-learning path and cleaned up stale bridge task-shaped plumbing that no longer matched the active TUI architecture.
- Tightened the Python codebase with behavior-preserving type and lint cleanup across the Hermit runtime, MCP adapter path, provider interfaces, install flow, interaction helpers, and supporting tests until `mypy hermit_agent` and `ruff check hermit_agent tests` passed cleanly.

## v0.3.7

### Documentation refresh — dual-orchestrator positioning
- Updated README tagline, diagram, and comparison table to reflect that Hermit works with both Claude Code and Codex as orchestrators (not just Claude Code).
- Updated `pyproject.toml` and `package.json` descriptions to mention both orchestrators.
- Added CHANGELOG entries for v0.3.5 and v0.3.6 that were previously missing.

## v0.3.6

### npm wrapper self-update and UX
- Added `hermit self-update` command to upgrade the npm-installed launcher.
- Launcher now prints a compact update hint on stderr when a newer version is detected.

## v0.3.5

### npm-first install support
- Published `@cafitac/hermit-agent` to npm as a thin launcher.
- On first run, bootstraps a managed Python runtime under `~/.hermit/npm-runtime`, installs `cafitac-hermit-agent` from PyPI, and forwards to the normal Hermit CLI.
- Added `hermit setup-codex` and `hermit setup-claude` entrypoints for split install paths.
- Clone-free install: `npm install -g @cafitac/hermit-agent && hermit setup-codex`.

## v0.3.4

### CI compatibility fixes
- Restored the truncation constants expected by `tests/test_task_result_handoff.py` through `hermit_agent.mcp_server`.
- Fixed `interaction_presenter.py` so the permission-summary formatting compiles cleanly on Python 3.11.

## v0.3.3

### Release metadata and install docs
- Clarified README install instructions so the published PyPI distribution name is `cafitac-hermit-agent` while the installed CLI commands remain `hermit`, `hermit-agent`, `hermit-gateway`, and `hermit-setup`.
- Updated package description and search keywords to reflect the current Hermit positioning: Claude Code remains the orchestrator while Hermit provides the Codex-aware MCP executor path.

## v0.3.2

### Package metadata alignment
- Renamed the published PyPI package metadata from `hermit-agent` to `cafitac-hermit-agent` so releases target the project that is actually owned and configured for publishing.
- Kept the installed CLI entrypoints (`hermit`, `hermit-agent`, `hermit-gateway`, `hermit-setup`) unchanged while only adjusting package metadata for distribution.

## v0.3.1

### Codex interaction cleanup
- Removed product-CLI-only Codex smoke subcommands after migrating their proof out of the main entrypoint.
- Preserved method-aware interaction routing in the live `hermit-channel` path instead of collapsing prompts to a prompt-kind-only model.
- Narrowed legacy Codex reply-hook cleanup so old hook removal does not delete unrelated `UserPromptSubmit` hooks.
- Removed the legacy Codex reply-hook runtime path and proof-only bridge leftovers that no longer contribute to the live interaction flow.

### Codex setup via Hermit
- Added an experimental `hermit-agent setup-codex` happy path that prepares Hermit's Codex integration, writes the needed project-local settings, and runs a local smoke check.
- Added installer/uninstaller hooks for Hermit's local Codex integration assets, including workspace marketplace cleanup and local async-interaction state removal.
- Added a thin internal Codex interaction adapter path so Codex approvals and free-text waits can flow through Hermit while preserving the existing Hermit reply queue fallback.
- Switched the happy path toward a package-first local runtime install, with local source-tree fallback kept only for development and unreleased-package scenarios.


## v0.3.0

### Configurable routing
- Added `routing.priority_models` in `settings.json` so users can define their own default model order instead of being locked to a built-in provider sequence.
- Set the default Codex lane to `gpt-5.4` with `medium` reasoning effort.
- Propagated Codex reasoning effort into the app-server turn start request.
- Updated docs to show JSON-based routing configuration and the new default chain.

## v0.2.1

### Documentation & release visibility
- Highlighted Codex support and default auto-routing behavior in `README.md`.
- Updated setup troubleshooting docs to show explicit routing rules and fallback order.
- Added `kb/` to `.gitignore` for local-only knowledge scratchpad files.

## v0.2.0

### Codex-first execution lane
- Added Codex app-server runner integration in Hermit gateway.
- Added strict explicit-model handling (`Requested model unavailable...`) instead of silent provider switching.
- Added default auto model routing when model is omitted: `codex -> z.ai -> local`.
- Fixed missing Codex done SSE publish path so channel completion notifications are emitted.
- Added tests for Codex runner, waiting payloads, and routing behavior.
