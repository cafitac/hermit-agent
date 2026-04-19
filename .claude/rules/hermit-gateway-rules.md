# HermitAgent Gateway-specific Rules

Applies only to `hermit_agent/gateway/` package.

## Gateway Responsibilities (Included) [P1]

- LLM relay (Ollama/z.ai/OpenAI compatible) — protocol conversion + routing.
- Model routing: name-prefix-based provider selection via `hermit_agent/gateway/routing.py::resolve_platform` (`name:tag` → ollama, `glm-*` → z.ai; extensible).
- **Two wire-format endpoints**: `/v1/chat/completions` (OpenAI-native) + `/anthropic/v1/messages` (Anthropic-native). Both go through the same provider adapter layer.
- **Per-key platform ACL**: `platforms` + `api_key_platform` tables with default-deny semantics. A key with zero rows is forbidden from all platforms.
- **Anthropic↔OpenAI text-only translator** (`hermit_agent/gateway/providers/anthropic_translator.py`) — bridges ollama (OpenAI-only) to the Anthropic endpoint. `tool_use` / `tool_result` → 400 in v1.
- Token-saving classifier, 429 failover, prompt cache hints, rate limit, auth token management.

## Gateway Responsibilities (Excluded) [P1]

- **No harness primitives** — CLAUDE.md loader, hooks, skills, permissions. These belong in `hermit_agent/` upper layer.
- **No HERMIT.md reading** — Gateway is stateless relay only.
- **No user experience features** — progress rendering, session saving, UI prompts.

## Error Handling [P1]

### 429 / Rate Limit
- On first attempt failure: short backoff then immediate failover. Avoid long backoff (looks like a hang). max_retries 3, timeout 120s.

### 5xx
- 1 retry with same provider → failover on failure. Log provider_id, request_id, status_code.

## Configuration Management [P2]

- All runtime settings are loaded via `hermit_agent/config.py::load_settings()`. No hardcoded URLs/keys.
- `~/.hermit/settings.json` is the single source of truth — `.env` files are not read by the launchers.
- New provider: (1) `LLMClientBase` impl, (2) name-prefix mapping, (3) add to the provider menu in `install.sh` and document it in `README.md`.

## Testing [P2]

- No real network calls — mock httpx/requests.
- Test 429/5xx/timeout paths. Follow patterns in `tests/test_llm_retry.py`, `test_llm_timeout.py`, `test_model_routing.py`.
