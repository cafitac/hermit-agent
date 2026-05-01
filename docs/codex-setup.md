# Register HermitAgent as a Codex executor lane

This guide is specifically for Codex. If you want Claude Code or Hermes Agent instead, use `docs/cc-setup.md` or `docs/hermes-setup.md`.

## What gets wired

Hermit's Codex setup currently focuses on setup and health:
- install or refresh the `codex-channels` runtime Hermit expects
- register Hermit in Codex's marketplace/runtime path
- register the `hermit-channel` MCP entry for Codex
- remove the legacy reply hook when present

Current boundary note:
- The live task runtime still flows through Hermit's existing MCP server and Codex-side runtime path.
- The adapter layer here is about setup/health truthfulness, not a new standalone runtime.

## 1. Install Hermit

```bash
npm install -g @cafitac/hermit-agent
hermit
```

Requires Node.js 20+ and Python 3.11+.

## 2. Run the guided install

For most users, the supported path is:

```bash
hermit install
```

For a non-interactive repair/setup pass:

```bash
hermit install --yes
```

If you are running CI or smoke checks and do not want optional agent-learner hook work:

```bash
hermit install --yes --skip-agent-learner
```

## 3. What success looks like

A healthy Codex-oriented setup should leave you with:
- a working Hermit managed runtime under `~/.hermit/`
- `codex-channels` runtime installed
- Codex marketplace/runtime registration refreshed when needed
- Codex-facing MCP surface still named `hermit-channel`

Hermit's doctor and status surfaces should report Codex readiness in setup terms such as `installed` rather than pretending the runtime boundary moved somewhere else.

## 4. Verification

Recommended checks:

```bash
hermit doctor
hermit status
```

If setup succeeded but Codex still does not pick the integration up, restart Codex after install so it reloads the refreshed registration.

## 5. Troubleshooting

| Symptom | What to do |
|---|---|
| Codex integration reports missing | Re-run `hermit install` or `hermit install --yes`, then check `hermit doctor` |
| Codex still behaves like Hermit is absent after install | Restart Codex so it reloads the refreshed registration |
| You see old reply-hook behavior or stale configuration | Re-run `hermit install`; the current flow removes the legacy Codex reply hook when present |
| You want a Claude Code-style slash command experience | That is still the most polished path today; see `docs/cc-setup.md` and `docs/hermit-variants.md` |

## 6. Scope clarification

This document is intentionally narrow:
- it does not claim Codex uses a brand-new Hermit runtime boundary
- it does not replace Codex as planner/reviewer
- it does describe the setup/health surfaces Hermit currently verifies and repairs

The important operator expectation remains simple: Codex should connect to Hermit through the `hermit-channel` MCP-facing surface while Hermit handles the repetitive repo execution underneath.