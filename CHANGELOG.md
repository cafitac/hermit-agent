# Changelog

## Unreleased

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
