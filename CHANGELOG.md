# Changelog

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
