# HermitAgent Known Issues and Stabilization Tasks

> Last updated: 2026-05-01

## Known Issues

### 1. Waiting Notification Loss [P1]

**Symptom**: When HermitAgent transitions to `waiting` state (for example a permission request or interview question), the notification can occasionally fail to surface in the Claude Code session, causing the task to wait longer than expected.

**Cause**: `_send_channel_notification()` is still fire-and-forget. If Claude Code drops the frame at that exact moment, the notification is lost.

**Current mitigation**: Retry logic in `hermit_agent/mcp_server.py` now re-sends `waiting` notifications until the task moves back to `running` or reaches a terminal state.

**Status**: Improved but still worth monitoring in real sessions.

---

### 2. Hermes CLI MCP smoke can look successful even when the probe text says otherwise [P1]

**Symptom**: `hermes mcp test hermit-channel` may print failure or cancellation text while still exiting with status code 0.

**Why it matters**: Naive shell automation can misread the integration as healthy.

**Current mitigation**: Hermit's `hermit install --test-hermes-mcp` smoke wraps the Hermes CLI probe and treats known failure text as a failed verification, even when Hermes exits 0.

**Status**: Public docs now recommend `hermit install --test-hermes-mcp` as the safer readiness check.

---

### 3. /tmp Disk Accumulation [P2]

**Symptom**: As Claude Code runs longer, task output files accumulate under `/private/tmp/claude-501/`, eventually causing ENOSPC.

**Cause**: Claude Code captures bash command output to files, but cleanup on session end appears incomplete.

**Next step**: Confirm the exact upstream behavior, then either file a Claude Code issue or add a bounded cleanup helper.

**Status**: Unresolved. Restart-time cleanup is still the temporary mitigation.

---

## Future Considerations

### Extended Thinking Introduction Review [P3 — After Mac Studio]

**Background**: Claude Code displays extended thinking as `⏺ Thinking / Working through it…`. qwen3-coder:30b also supports thinking mode via `/******/` tags and can be activated in ollama with the `think: true` option.

**Expected Improvements**:
- Reduction of errors requiring chain tracing, such as incorrect mock paths
- Reduction of context loops (repeating the same question)
- Improved quality of complex state transition/concurrency judgments

**Reasons for Postponing Introduction**:
- Enabling thinking on 30B model increases response time to 1–2 minutes significantly
- Concern about reduced effective work output given max_turns 200
- Need to add `/******/` tag parsing/stripping in loop.py

**Review Timing**: Consider introduction when switching to 70B+ model after Mac Studio arrival (2026-09).

---

### MLX Backend Switch Review [P3 — After Mac Studio]

**Background**: Apple's MLX framework (`mlx-lm`) is optimized for Apple Silicon unified memory, offering faster inference than llama.cpp (ollama). `mlx-lm.server` provides an OpenAI-compatible API, so HermitAgent only needs to change `HERMIT_LLM_URL` to connect.

**Expected Improvements**:
- Faster inference for the same model (faster than llama.cpp on Apple Silicon)
- Direct use of HuggingFace Hub models (no cost, many converted models in `mlx-community` organization)
- Ability to run 70B+ models at more practical speeds

**Switch Method (Reference)**:
```bash
pip install mlx-lm

# Run server (OpenAI compatible :8080)
mlx_lm.server --model mlx-community/Qwen2.5-Coder-32B-Instruct-4bit --port 8080

# Connect HermitAgent
HERMIT_LLM_URL=http://localhost:8080/v1
```

**Review Timing**: Decide after speed comparison with ollama after Mac Studio arrival (2026-09).

---

## Recurrence Prevention Notes

- **MCP server restart impact**: modifying the MCP server code requires restarting the MCP transport; Claude Code will not auto-reconnect. Prefer applying changes when no tasks are in progress, and use `/mcp` to reconnect if needed.
- **Incorrect cwd**: Passing a parent directory as `cwd` when running `/feature-develop` causes relative-path errors. Set `cwd` to the exact project root (for example `$HOME/Project/<your-repo>`), not a parent directory.
- **Hermes readiness probes**: when documenting Hermes setup, prefer Hermit's wrapper commands (`--print-hermes-mcp-config`, `--fix-hermes-mcp`, `--test-hermes-mcp`) over raw shell automation that only checks the Hermes CLI exit code.
