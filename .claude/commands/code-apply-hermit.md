# /code-apply-hermit — Claude reads the review, Hermit applies it

Hands the P1–P5 findings from the most recent `/code-review` to Hermit
so Claude doesn't burn tokens re-reading every file and retyping every
edit. Claude stays on judgment; Hermit does the mechanical apply.

## Arguments

`$ARGUMENTS` — PR number, optionally followed by severity filters.
Examples: `123`, `123 P1 P2 P3`.

- `--model <model_name>` — which executor model Hermit should run.
  Defaults to the gateway's active model
  (`./bin/gateway.sh --status` to see the current pick).

## Prerequisites

- A `/code-review` output from the previous turn in this conversation.
- Hermit gateway + MCP server running.

## Workflow

### Step 1 — locate the worktree

If the argument contains a PR number, follow the repo's worktree
convention to resolve the worktree path (or infer from the current
branch if you are already inside it). If no worktree / PR info can
be resolved, ask the user which directory to operate on.

### Step 2 — harvest review findings

Scan the prior conversation for the last `/code-review` output and
extract each finding: severity, file path, line number, description,
and the proposed direction.

If no review output is present, stop and tell the user to run
`/code-review $ARGUMENTS` first.

### Step 3 — choose what to apply

- Default: every P1 through P5 item.
- Filter: if severities are listed in `$ARGUMENTS` (e.g. `P1 P2`),
  apply only those.

### Step 3.5 — write findings to disk

Save the selected findings to:

```
.omc/reviews/<branch>-review-<YYYYMMDDHHMMSS>.md
```

Format:

```markdown
# Code Review Findings — <branch>

## P1
- `path/to/file.py:42` — short description — suggested fix

## P2
- ...
```

### Step 4 — concurrency lock

```bash
mkdir -p .hermit
cat > .hermit/active-task.lock <<EOF
{
  "task_id": "<filled-after-run_task>",
  "started_at": "$(date -Iseconds)",
  "skill": "code-apply-hermit",
  "pr": "$ARGUMENTS",
  "cwd": "<worktree_path>",
  "findings": "<findings_file_path>"
}
EOF
```

### Step 5 — delegate via `mcp__hermit__run_task`

`cwd = <worktree>`, `background = true`, `model = <--model value or "">`.

```
You are Hermit. Apply code review findings inside this worktree.

Findings: <absolute path to the findings file>

Rules:
1. Read the findings file first, then apply every item it lists.
2. Per file touched: preserve existing behaviour — never silently drop
   validation, error handling, or cleanup.
3. If a fix direction is ambiguous, call ask_user_question (the
   channel relays it to Claude).
4. After modifying a file, scan sibling files for the same issue
   (same-interface refactoring scope). Fix matching cases too.
5. Do NOT commit or push — Claude handles git.
6. Obey HERMIT.md, .hermit/rules/, and .claude/rules/.

Completion:
- All findings applied.
- Project test runner passes (run it yourself before finishing).
- Return: files changed, findings addressed by ID, anything skipped
  with a reason.
```

Immediately after `run_task` returns, call
`mcp__hermit-channel__register_task(task_id)` and update the lock.

### Step 6 — monitor progress

- `waiting` → relay Hermit's question to the user, collect the
  answer, forward with `reply_task`.
- `running` → only call `check_task` if the user asks.
- `done` → proceed to Step 7.
- `failed` → report and offer retry / Claude takeover / cancel.

### Step 7 — verify and release

1. Pull the summary from `check_task`.
2. **Scope guard** (same as pure `/code-apply`):
   - Compute the PR's in-scope files from the GitHub diff.
   - If the worktree touched files outside that set, revert them with
     `git checkout <base-branch> -- <path>`.
3. Re-run the project's test runner in a `run_in_background`
   subagent.
4. Delete `.hermit/active-task.lock`.

### Step 8 — summary

```
## /code-apply-hermit complete

### Applied
- [P1] `path:line` — description (done)
- [P2] `path:line` — description (done)

### Additional same-pattern fixes
- `path` — expanded pattern applied.

### Tests
- X passed

### Out-of-scope reverts
- (none) or list of files
```

## Safety rules

- Create the lock before delegating; delete it on completion.
- No Claude edits while the lock exists (hook-enforced).
- Refuse to run without a prior `/code-review` output.
- Hermit must not commit or push.
- Out-of-scope changes are auto-reverted.
- **No compound shell commands**: use `git -C <path> ...`, not
  `cd <path> && git ...`.
