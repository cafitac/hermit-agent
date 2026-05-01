# Contributing to HermitAgent

Thanks for looking. HermitAgent is small and opinionated — contributions are welcome but expect some taste calls.

## Dev setup

```bash
git clone https://github.com/cafitac/hermit-agent.git
cd hermit-agent
./install.sh              # creates .venv, bootstraps uv, installs the project editable with the test extras
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

The root GitHub Actions workflow (`.github/workflows/python-tests.yml`) uses the same editable install + `.venv/bin/python -m pytest tests/` contract.

## Running tests

```bash
.venv/bin/python -m pytest tests/                              # whole suite; ollama-dependent tests skipped via conftest.py
.venv/bin/python -m pytest tests/test_loop_guards.py -v         # targeted
.venv/bin/python -m pytest tests/ -k "learner"                  # by keyword
```

Prefer `python -m pytest` over the direct `.venv/bin/pytest` script so the active interpreter is explicit and stale entrypoint shebangs cannot select the wrong Python.

No network calls in tests. `httpx` / `requests` should be mocked. See `tests/test_llm_retry.py` for the pattern.

## Style

- Python 3.11+
- If you already have them installed locally, `ruff format` then `ruff check`
- If you already have it installed locally, `mypy hermit_agent/` should be clean
- The `.claude/hooks/python-syntax-check.sh` PostToolUse hook catches obvious breakage when Claude Code edits a file — install it in your CC config if you want the same guard

No opinions on line length beyond "ruff defaults."

## Architecture rules

Read `.claude/rules/hermit-conventions.md` and `.claude/rules/hermit-gateway-rules.md` before deep changes. Short version:

- `src/` is read-only (Claude Code reference mirror). Never modify.
- `hermit_agent/gateway/` is the LLM relay layer. Do not put harness primitives (CLAUDE.md loading, hooks, skills, permissions) in there.
- `hermit_agent/` is the agent. Stays provider-agnostic.
- Layered: view → service → model → infra. Cross-layer shortcuts are reviewed hard.
- TDD for non-trivial changes. Red-green-verify, not test-after.
- Guardrail profiles live under `hermit_agent/profiles/defaults/`; local machine overrides belong in `~/.hermit/profiles/` and should not be committed.

## Pull requests

1. Branch from `main`.
2. Keep PRs focused. If you are fixing two things, that is two PRs.
3. Include tests. If a test cannot reasonably be written, say so in the PR body.
4. Describe **what changed and why**, not **what the PR does** — the diff already shows that.
5. For UI or behaviour changes, include a before/after example or a test exercising the path.

Commit messages: imperative English, conventional prefix optional (`feat:` / `fix:` / `refactor:` / `docs:` / `chore:` / `test:`). Do **not** include `Co-Authored-By` lines unless a human collaborator actually co-authored.

## What gets merged fast

- Bug fixes with a failing test attached
- Doc clarifications
- Provider adapters (add a new LLM backend in `hermit_agent/llm_client.py`, plus routing in `hermit_agent/gateway/task_runner.py`, plus tests)
- Tool additions that are small and self-contained under `hermit_agent/tools/`
- Benchmark datapoints under `benchmarks/results/` — see [benchmarks/README.md](benchmarks/README.md)

## What needs discussion first

- New slash commands / `-hermit` skill variants
- Changes to the learner lifecycle (open an issue referencing `.dev/learner-spec.md`)
- Anything touching permissions defaults
- Anything touching the harness layering

For those, open an issue (use the Feature template) before the PR so the design can be discussed once.

## Issues

- Use the Bug template for reproducible issues; include the command you ran, the output, and `python --version`.
- Use the Feature template for proposals; explain the problem first, then the suggestion.
- "Question" issues are fine if you cannot find an answer in the code.

## Code of conduct

Be respectful. Disagree on technical grounds, not personal ones. That is the whole policy.
