# /feature-develop-hermit — Claude plans, Hermit implements

Same outline as `/feature-develop`, but the **Phase 3 implementation**
is delegated to Hermit over MCP so Claude's context never absorbs the
grunt-work tool output.

Claude is the orchestrator (interview, pattern search, plan, final
verification). Hermit is the executor (TDD red-green implementation).

## Arguments

`$ARGUMENTS` — PR number (or a short slug if you are not using GitHub PRs).

- `--strategy {aggressive|moderate|conservative}` — delegation depth.
  If omitted, inferred from the model-strategy map in the checkpoint
  config (see "Checkpoint policy").
- `--model <model_name>` — which executor model Hermit should run with
  (e.g. `--model glm-5.1`, `--model qwen3-coder:30b`). If omitted, the
  gateway's default model is used.

## Checkpoint policy

The delegation depth is read from:

```
$HERMIT_CHECKPOINT_CONFIG  (env override)
  ├── ~/.claude/state/hermit-checkpoints.json  (user-local)
  └── scripts/harness/hermit-checkpoints.default.json  (repo default)
```

### Three strategies

| Strategy | Claude does | Hermit does |
|---|---|---|
| `aggressive` | interview · plan review · final verify | pattern search · plan doc · implementation |
| `moderate` | interview · pattern search · plan review · final verify | plan doc · implementation |
| `conservative` | interview · pattern search · plan doc · plan review · final verify | implementation only |

### Auto-selection

If `--strategy` is absent, query the gateway's active model
(`./bin/gateway.sh --status` or `GET /health → active_models[0]`) and look
it up in the config's `model_strategy_map`:

- Prefix or substring match (e.g. `glm-5.1` → `glm` → `aggressive`)
- If nothing matches, fall back to `default_strategy`.

## Prerequisites

- `gh` CLI authenticated (or skip the GitHub steps if you don't use it)
- Hermit gateway + MCP server running (`./bin/gateway.sh --status`)
- Current branch is the PR branch, or the worktree already exists

## Workflow

### Phase 0 — fetch PR context (Claude)

Use a `general-purpose` subagent to run `gh pr view` and prepare the
worktree. Identical to `/feature-develop` Phase 0.

### Phase 0.5 — plan consensus (Claude)

`Skill("oh-my-claudecode:ralplan")` for a multi-LLM consensus on the
interview direction.

### Phase 1 — implementation interview (Claude)

`Skill("oh-my-claudecode:deep-interview")` until ambiguity ≤ 20 %.
The spec is written to `.omc/specs/deep-interview-<slug>.md`.

### Phase 1.5 — pattern search

- **Default** (Claude): 2-3 Explore subagents run in parallel to collect
  service / model / test patterns. Result: `.omc/plans/<branch>-patterns.md`.
- **`--aggressive` or `--moderate`**: Hermit writes the patterns file as
  part of Phase 3.

### Phase 2 — planning document

- **Default** (Claude): haiku subagent writes `.omc/plans/<branch>.md`.
- **`--aggressive`**: Hermit writes the plan doc.

### Phase 2.5 — plan approval gate

When Hermit produces the plan + patterns docs, it **stops and waits**
via `ask_user_question` before implementing. Claude verifies:

1. Every decision in `plan.md` has a justification (reference file,
   line numbers, pattern rationale).
2. Claimed patterns match the referenced files (sample check).
3. No edge cases from the interview are missing.
4. No out-of-scope suggestions slipped in.

Decision:
- **Approve** → Claude replies `proceed`; Hermit enters Phase 3.
- **Revise** → Claude sends concrete revisions; Hermit updates and
  re-checks.
- **Reject** → release the lock and take over manually.

### Phase 3 — Hermit implementation (the core)

#### 3.1 Concurrency lock

Before delegating, create an editor-lock so Claude's `Edit`/`Write`
calls are blocked by `.claude/hooks/block-during-hermit.sh` (reads are
still fine):

```bash
mkdir -p .hermit
cat > .hermit/active-task.lock <<EOF
{
  "task_id": "<filled-in-after-run_task>",
  "started_at": "$(date -Iseconds)",
  "skill": "feature-develop-hermit",
  "pr": "$ARGUMENTS",
  "cwd": "<worktree_path>"
}
EOF
```

#### 3.2 Delegate via `mcp__hermit__run_task`

- `cwd`: the worktree path chosen in Phase 0
- `background`: `true` (so Claude can handle other requests while
  Hermit works)
- `model`: value of `--model`, or `""` for the gateway default
- `prompt`: see the templates below

**Baseline prompt (plan + patterns already exist):**

```
You are Hermit. Implement Phase 3 of /feature-develop for PR
#<PR-number> in this worktree.

Spec:     <abs path>/.omc/specs/deep-interview-<slug>.md
Plan:     <abs path>/.omc/plans/<branch>.md
Patterns: <abs path>/.omc/plans/<branch>-patterns.md

Read all three first, then follow the plan's numbered steps.

Rules:
1. TDD red-green — write the failing test first, implement, verify
   `pytest` (or the project's test runner) passes.
2. Do NOT invoke /code-review, /code-polish, or any sibling skill.
3. Do NOT commit or push. Edit files only. Claude handles git.
4. Obey HERMIT.md, .hermit/rules/, and .claude/rules/.
5. Preserve existing behaviour — never silently drop validation,
   error handling, or cleanup.
6. If a decision is ambiguous, call ask_user_question (the channel
   routes it back to Claude).
7. On unrecoverable failure: stop and report. Do not retry forever.

Completion:
- All plan steps implemented
- Tests pass
- Return: files changed, tests added, anything skipped (with reason).
```

**Aggressive / moderate prompt (Hermit produces the plan, too):**

Before implementing, Hermit produces two artefacts:

```
1. .omc/plans/<branch>-patterns.md — 3–5 reference files with absolute
   paths, line ranges, and 10–30-line snippets; classified by domain,
   infrastructure, service layer, or test structure.

2. .omc/plans/<branch>.md — planning doc.

Enforced: every decision MUST include
- "Source: path/to/file.py:L42-L58"
- "Rationale: 1–2 sentences"
- "Alternative considered + why rejected"

Plans without these three fields are returned for revision.

3. STOP and call ask_user_question:
     question: "Plan ready for review. Approve or revise?"
     options: ["approve", "revise"]

Wait for Claude's reply. Only proceed to implementation on `approve`.
On `revise`, incorporate the feedback, regenerate, and ask again.
```

#### 3.3 Register the task

After `run_task` returns a `task_id`, **immediately** call
`mcp__hermit-channel__register_task(task_id)` and update the lock file.

Claude then handles:

- `status: "waiting"` → relay Hermit's question to the user, collect
  the answer, forward with `reply_task`
- `status: "running"` → only call `check_task` when the user asks
- `status: "done"` → advance to Phase 4
- `status: "failed"` → go to Phase 3.5

#### 3.4 Claude is free while the task runs

Because the task is backgrounded, Claude can continue other
conversation in the same session — but `Edit` and `Write` are locked.
For unrelated edits, cancel first (`/hermit-cancel`).

### Phase 3.5 — failure handling (optional)

On `status: "failed"`, report the failure summary and offer:

- **Retry** — re-run `run_task` with the same prompt.
- **Resume** — same spec/plan, "resume from step N" prompt.
- **Take over** — clear the lock, Claude does Phase 3 itself
  (the pure `/feature-develop` fallback).
- **Cancel** — clear the lock, abandon.

### Phase 4 — verify and release the lock

1. Read the implementation summary from `check_task`.
2. **Claude verification**:
   - `git diff --stat` to sanity-check scope.
   - Re-run tests via the project's test runner in a `run_in_background`
     subagent.
   - Confirm no files outside the PR scope changed.
3. Delete `.hermit/active-task.lock`.
4. Report:

```
## /feature-develop-hermit complete

- PR: #$ARGUMENTS — [title]
- Branch: <branch>
- Worktree: .worktrees/<branch>
- Steps implemented (by Hermit):
  - Step 1: ...
  - Step 2: ...
- Tests: pass / fail
- Plan doc: .omc/plans/<branch>.md
- Suggested next step: /code-qa $ARGUMENTS
```

## Safety rules

- **No Hermit call without a lock** — always create the lock first.
- **No Claude edits while the lock exists** — the hook enforces this.
- **Do not advance to Phase 4 if tests fail** — offer retry instead.
- **Hermit does not commit or push** — that's for `/code-push` or
  `/code-push-hermit` later.
- All the standard `/feature-develop` guardrails still apply
  (never work directly on `main`/`develop`, etc.).

## Difference vs pure `/feature-develop`

| Item | `/feature-develop` | `/feature-develop-hermit` |
|---|---|---|
| Interview | Claude | Claude (same) |
| Pattern search | Claude | Claude (or Hermit with `--aggressive`) |
| Plan doc | Claude | Claude (or Hermit with `--aggressive`) |
| **Implementation** | **Claude** | **Hermit** |
| Claude tokens | High | Low (implementation is the hot spot) |
| Wall-clock | Fast | Bound by the executor's speed |
| Backgrounded | No | Yes (Claude stays conversational) |
