# Hermit open-source positioning

This file keeps the short public-facing copy for repository metadata, launch posts, release blurbs, and future social preview work.

## One-line description

MCP executor for Claude Code or Codex that offloads repetitive coding work to cheaper local or flat-rate models.

## Short pitch

Hermit adds a dedicated execution lane to your coding-agent stack. Keep Claude Code or Codex for planning, judgment, and review; let Hermit carry the mechanical repo work through MCP with predictable local or flat-rate routing.

## What makes Hermit different

- It is not another planner trying to replace Claude Code or Codex.
- It is an executor layer that turns orchestrator intent into edits, tests, commits, and release follow-through.
- It defaults toward cost-predictable local or flat-rate models instead of surprising hosted fallback behavior.
- It works across multiple orchestrators, which makes it easier to adopt as shared team infrastructure.

## Audience fit

### Great fit
- Teams already invested in Claude Code or Codex that want a dedicated execution lane.
- Repositories where test runs, refactors, commits, and release chores are burning expensive planner tokens.
- Maintainers who want one MCP executor path shared across multiple orchestrators.

### Weak fit
- Users who want Hermit itself to be the premium planner.
- Teams that are happy with one hosted model doing both judgment and execution.
- Very small workflows where planner/executor separation adds more ceremony than value.

## Social preview copy ideas

### Option A
Premium reasoning on top, cheap execution underneath.
Hermit is the MCP executor layer for Claude Code and Codex.

### Option B
Keep your best model for judgment.
Use Hermit for the repetitive coding work.

### Option C
Claude Code or Codex plans.
Hermit executes.
Your bill stays predictable.

## Homepage / hero copy variants

### Variant A
Keep the premium orchestrator for judgment.
Use Hermit for the repetitive repo work.

### Variant B
Claude Code or Codex thinks.
Hermit ships the mechanical follow-through.

### Variant C
One MCP executor layer.
Cheaper execution across multiple orchestrators.

## Social preview asset

- Final editable asset: `docs/assets/hermit-social-preview.svg`
- Ready-to-upload export: `docs/assets/hermit-social-preview.png`
- Local review page: `docs/assets/hermit-social-preview-review.html`
- Operating guide: `docs/social-preview-ops.md`
- Intended use: GitHub social preview image export, release cards, launch posts, and docs screenshots.
- Design direction: dark terminal-like card, premium planner on top, cheaper execution lane underneath, no provider-specific billing claims beyond predictable local / flat-rate defaults.
- Message hierarchy: plan with Claude Code or Codex, execute repetitive repo work with Hermit, and reinforce predictable local / flat-rate routing on the supporting side of the card.

## Release-note framing

Hermit helps teams separate high-value reasoning from high-volume execution. That means better cost control, cleaner planner/executor boundaries, and an MCP-native path from idea to tested repo change.
