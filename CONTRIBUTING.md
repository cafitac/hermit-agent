# Contributing to Hermit

Hermit is a small MCP coding executor for Claude Code, Codex, and Claude
Desktop. Keep changes focused on the four public task tools and the minimal
host-installation paths.

## Dev setup

```bash
git clone https://github.com/cafitac/hermit-agent.git
cd hermit-agent
./install.sh
```

Prefer to run the steps yourself:

```bash
python -m venv .venv
.venv/bin/pip install uv
.venv/bin/uv pip install -e '.[test]'
```

If you want the optional local tooling mentioned below, install the dev extra instead:

```bash
.venv/bin/uv pip install -e '.[dev]'
```

## Running tests

```bash
.venv/bin/python -m pytest tests/
.venv/bin/python -m pytest tests/test_mcp_install.py -v
```

Prefer `python -m pytest` over the direct `.venv/bin/pytest` script so the active interpreter is explicit and stale entrypoint shebangs cannot select the wrong Python.

No network calls in tests. `httpx` / `requests` should be mocked. See `tests/test_llm_retry.py` for the pattern.

## Style

- Python 3.11+
- Run `ruff format` then `ruff check` when available.
- Keep the MCP process stdio-only; background execution belongs in the gateway.
- When changing the Desktop bundle, run `python scripts/build_mcpb.py` and keep
  its manifest, matching PyPI version, and tests in the same change.

No opinions on line length beyond "ruff defaults."

## Pull requests

1. Branch from `main`.
2. Keep PRs focused. If you are fixing two things, that is two PRs.
3. Include tests. If a test cannot reasonably be written, say so in the PR body.
4. Describe **what changed and why**, not **what the PR does** — the diff already shows that.
5. Include a test that exercises changed behaviour.

Commit messages: imperative English, conventional prefix optional (`feat:` / `fix:` / `refactor:` / `docs:` / `chore:` / `test:`). Do **not** include `Co-Authored-By` lines unless a human collaborator actually co-authored.

## What gets merged fast

- Bug fixes with a failing test attached
- Doc clarifications
- Gateway or MCP bug fixes with a regression test
- Documentation improvements to the install and use flow

## What needs discussion first

- New public MCP tools
- Changes to permissions defaults or executor routing

For those, open an issue (use the Feature template) before the PR so the design can be discussed once.

## Issues

- Use the Bug template for reproducible issues; include the command you ran, the output, and `python --version`.
- Use the Feature template for proposals; explain the problem first, then the suggestion.
- "Question" issues are fine if you cannot find an answer in the code.

## Code of conduct

Be respectful. Disagree on technical grounds, not personal ones. That is the whole policy.
