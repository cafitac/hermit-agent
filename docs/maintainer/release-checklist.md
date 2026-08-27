# v0.4.x host acceptance checklist

Run this checklist for each release candidate outside the ordinary user README
flow. Record versions and pass/fail results only; never paste settings files,
API keys, gateway keys, or raw environment variables into an issue or release
note.

Use either a ready local Ollama coder model or an OpenAI-compatible endpoint.
For a remote endpoint, keep its credential in the shell or operating-system
secret store and use `hermit configure --api-key-env NAME`; the key itself must
never be passed to Hermit on the command line.

## Claude Code

1. Install the candidate: `npm install -g @cafitac/hermit-agent@<version>`.
2. Configure the executor, run `hermit install claude`, then run
   `hermit doctor --json`. Confirm `hosts.claude_code`, `gateway.status`, and
   `executor.status` separately show readiness.
3. Restart Claude Code. Use `run_task` for one bounded repository change.
4. Poll the returned ID with `check_task` until completion, and verify the
   resulting change and focused test locally.

## Codex

1. Install the candidate: `npm install -g @cafitac/hermit-agent@<version>`.
2. Configure the executor, run `hermit install codex`, then run
   `hermit doctor --json`. Confirm `hosts.codex`, `gateway.status`, and
   `executor.status` separately show readiness.
3. Restart the Codex CLI, desktop app, or IDE extension being accepted. Use
   `run_task` for one bounded repository change.
4. Poll the returned ID with `check_task` until completion, and verify the
   resulting change and focused test locally.

## Claude Desktop

1. Download the release's `hermit-<version>.mcpb` asset and install it through
   **Settings → Extensions → Advanced settings → Install Extension** (or open
   the file with Claude Desktop).
2. Configure a ready executor. If using the extension's optional remote
   credential field, use a disposable acceptance-test credential and do not
   record it. Close and reopen Claude Desktop; confirm the credential is not
   written to `~/.hermit/settings.json`.
3. Confirm the extension exposes exactly four Hermit tools:
   `run_task`, `reply_task`, `check_task`, and `cancel_task`.
4. Run one bounded `run_task`, poll it with `check_task`, and verify the
   resulting change and focused test locally.

## Release gate

Before approving a public release, the CI workflow must pass Python 3.11,
3.12, and 3.13 tests; compile and package checks; wheel/sdist and MCPB
verification; and a clean public npm installation that bootstraps PyPI then
completes an MCP stdio handshake with exactly the four tools above.
