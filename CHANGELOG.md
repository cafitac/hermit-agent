# Changelog

## Unreleased

### Repository positioning and metadata
- Refreshed the README opening section to position Hermit as a distinct open-source executor layer for Claude Code and Codex rather than a generic terminal UI.
- Added a comparison section that explains why teams would pair Hermit with Claude Code or Codex instead of treating it as a replacement orchestrator.
- Added explicit "who Hermit is for / not for" guidance so the landing page qualifies the intended audience instead of only describing features.
- Added a reusable `docs/open-source-positioning.md` copy deck for repository descriptions, social preview messaging, release framing, and audience-fit guidance.
- Added a final social-preview asset set: editable SVG, ready-to-upload PNG export, and a local review page under `docs/assets/` for GitHub/social-preview iteration.
- Added `docs/social-preview-ops.md` so maintainers have a concrete review/export/upload checklist for the GitHub social preview image.
- Updated package and repository-facing descriptions to emphasize the MCP executor + cheaper execution lane story instead of the outdated Codex-first fallback wording.
- Tightened the public metadata around predictable local / flat-rate defaults so the repository pitch matches the current install and routing policy.

### Release workflow safety
- `Publish npm + PyPI` now evaluates every `main` merge by default instead of relying on path-filtered triggers.
- Metadata-only version syncs (`pyproject.toml` + `hermit-ui/package.json`), release write-back commits, and explicit `[skip release]` commits are still skipped so the repo does not cut meaningless follow-up patch releases.
- Added a `classify_release` gate that skips release runs for release write-back commits and for explicit `[skip release]` commits.
- Made manual `workflow_dispatch` releases opt-in via `force_publish=true` so accidental button-clicks do not publish by default.
- Split the release automation into clearer stages: version determination, npm publish, PyPI publish, release-tag push, GitHub Release publication, and repository write-back / sync-PR fallback.
- Added a dedicated `Publish GitHub Release` workflow on `v*` tags for manual or external tag pushes, while the main release workflow also creates the GitHub Release directly so auto-published releases do not depend on cross-workflow tag triggers.
- Added release-workflow concurrency plus idempotent npm publish, tag-push, and GitHub Release checks so reruns do not accidentally create duplicate artifacts.
- Fixed release write-back to use the configured push token correctly, and kept the protected-`main` fallback that opens a sync PR when direct write-back is rejected.

### Install and model-selection UX
- Switched the primary onboarding flow to `npm install -g @cafitac/hermit-agent` followed by `hermit`, with guided setup offered from startup when Claude Code or Codex integration is incomplete.
- Added interactive startup update prompts for user-facing `hermit` commands so newer npm releases can be installed before continuing.
- Added install-time model preference selection so users can choose whether plain `hermit` follows auto-routing or stays pinned to a fixed model.
- Clarified the difference between `model` and `routing.priority_models`, and made plain `hermit` honor the routing priority chain when `model` is set to `__auto__`.
- Made the npm launcher sync the managed Python runtime to the same published Hermit version so new install/setup behavior is not hidden behind a stale backend package.

## v0.3.48

### GitHub Release automation and release-state alignment
- The main `Publish npm + PyPI` workflow now creates or updates the GitHub Release in the same run after pushing the release tag, so the primary auto-release path no longer depends on a second tag-triggered workflow firing.
- Kept a dedicated `Publish GitHub Release` workflow as a manual / fallback path for externally pushed tags and backfills.
- Confirmed the published npm package, PyPI package, release tag, GitHub Release, and repository version files all converge on `0.3.48` after the protected-`main` sync PR flow completes.

## v0.3.47

### Clearer release stages and safer protected-main write-back
- Split release automation into explicit stages for classification, tests, version determination, npm publish, PyPI publish, tag push, GitHub Release publication, and repository metadata write-back.
- Added release-sync PR fallback behavior when direct write-back to protected `main` is rejected by repository rulesets.
- Preserved metadata-only sync guards and explicit `[skip release]` markers so follow-up version-sync commits do not create meaningless extra patch releases.

## v0.3.44

### Auto-routing policy change
- `hermit install` no longer puts Codex (`gpt-5.4`) in the default `routing.priority_models` chain.
- The default executor auto-routing order is now `glm-5.1 -> qwen3-coder:30b`.
- Codex remains supported as an explicit opt-in path through `codex_default_model`, direct model pinning, or a user-customized routing chain.

### Why this changed
- Hermit's default job is executor work on cheaper local or flat-rate models.
- Automatic Codex fallback could route work onto a paid hosted model without the user explicitly choosing it.
- Keeping Codex available but out of the default auto-routing path makes cost behavior more predictable and keeps the planner/executor split clearer.

### Docs and install flow
- Updated installer presets so Codex auto-routing is only enabled by explicit user choice.
- Updated configuration examples and install docs to match the new default behavior.
- Added regression tests to keep the default routing policy from drifting back.

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
