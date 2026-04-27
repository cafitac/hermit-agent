# Release notes template

Use this template when publishing GitHub Releases, package announcements, or changelog summaries for Hermit.

## Short version

```md
## What changed
- [main user-visible change]
- [workflow or operator-facing change]
- [why it matters for cost, reliability, or usability]

## Why it matters
[one short paragraph connecting the change back to Hermit's planner/executor positioning]
```

## Full version

```md
## Summary
[One sentence: what changed in this release.]

## What changed
- [Change 1]
- [Change 2]
- [Change 3]

## Why it matters
[Explain how this improves planner/executor separation, cost predictability, release reliability, or day-to-day usability.]

## Operator notes
- [migration / config / rollout note]
- [verification or fallback note]

## Assets
- npm: https://www.npmjs.com/package/@cafitac/hermit-agent
- PyPI: https://pypi.org/project/cafitac-hermit-agent/
- README: https://github.com/cafitac/hermit-agent#readme
```

## Tone guidelines

- Lead with the user-facing outcome, not internal implementation detail.
- Use the same framing as the README and social preview: premium orchestrator for judgment, Hermit for repetitive repo execution.
- Prefer "predictable local or flat-rate execution" over provider-specific claims.
- Keep bullets concrete: edits, tests, commits, release follow-through, routing defaults, or maintainer workflow.
- If the release is mostly documentation or positioning, say that plainly instead of overselling it as core product capability.

## Reusable opening lines

- Hermit keeps Claude Code or Codex focused on judgment while offloading repetitive repo work to a dedicated MCP executor lane.
- This release sharpens the executor-layer experience: better operator guidance, clearer positioning, and more predictable follow-through.
- This update improves the public-facing story around Hermit's planner/executor split without changing its core role.

## Reusable closing lines

- Hermit continues to optimize for one job: cheaper, more predictable execution underneath a premium orchestrator.
- The planner stays premium; the repo mechanics stay efficient.
- The goal remains the same: better judgment up top, cheaper follow-through underneath.
