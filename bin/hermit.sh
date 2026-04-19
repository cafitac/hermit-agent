#!/bin/sh
# HermitAgent launcher — React+Ink UI + Python agent backend.
#
# Paths are auto-detected from this script's location. Override via
# environment variables if you keep the venv or UI elsewhere:
#   HERMIT_VENV_DIR  — Python virtualenv (default: $HERMIT_DIR/.venv)
#   HERMIT_UI_DIR    — React+Ink UI dir containing dist/app.js
#                      (default: $HERMIT_DIR/hermit-ui)
#
# Single-message CLI mode does not require the UI:
#   hermit "your message here"

set -e

# Resolve script directory portably (no realpath dependency).
SCRIPT="$0"
case "$SCRIPT" in
  /*) ;;
  *) SCRIPT="$PWD/$SCRIPT" ;;
esac
HERMIT_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT")/.." && pwd)

VENV_DIR="${HERMIT_VENV_DIR:-$HERMIT_DIR/.venv}"

if [ ! -d "$VENV_DIR" ]; then
  echo "Hermit venv not found at: $VENV_DIR" >&2
  echo "Create one with:" >&2
  echo "  python -m venv $HERMIT_DIR/.venv" >&2
  echo "  $HERMIT_DIR/.venv/bin/pip install -e $HERMIT_DIR" >&2
  echo "Or set HERMIT_VENV_DIR to an existing venv." >&2
  exit 1
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_SITE=$(ls -d "$VENV_DIR"/lib/python*/site-packages 2>/dev/null | head -1)

# Configuration lives in ~/.hermit/settings.json — installer writes
# it, runtime reads it via load_settings(). .env files are NOT read by
# the launchers (see ADR: single-source config). HERMIT_* env vars you
# `export` in your shell still override settings.json as a last
# resort, mostly useful for one-shot `HERMIT_MODEL=x hermit "..."`.

# Auto-start the gateway if it isn't already listening. The standalone
# CLI can run without it, but keeping the gateway warm means that if the
# user hops into a Claude Code session next, MCP/run_task traffic lands
# on something alive. Opt out with HERMIT_AUTO_GATEWAY=0.
_GW_URL="${HERMIT_GATEWAY_URL:-http://127.0.0.1:8765}"
if [ "${HERMIT_AUTO_GATEWAY:-1}" != "0" ]; then
  if ! curl -sf --max-time 1 "$_GW_URL/health" >/dev/null 2>&1; then
    echo "hermit: gateway not reachable at $_GW_URL — starting daemon..." >&2
    "$HERMIT_DIR/bin/gateway.sh" --daemon >/dev/null 2>&1 || \
      echo "hermit: gateway --daemon failed (see ~/.hermit/gateway.log); continuing anyway." >&2
    # Give it a moment to come up before the preflight below.
    for _i in 1 2 3 4 5; do
      curl -sf --max-time 1 "$_GW_URL/health" >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi
fi

# Preflight: bail out early with an actionable message when we can
# already tell the LLM will not respond. The two common cases:
#   a) model is an external provider (no `:`) but llm_api_key is empty
#   b) gateway /health reports components.llm.status == "major"
#      (endpoint unreachable, not a 4xx auth issue we can still learn
#      from). Exit 2 means "configuration problem, please fix" so it
#      is distinguishable from normal runtime errors.
if [ "${HERMIT_SKIP_PREFLIGHT:-0}" != "1" ]; then
  _PF_MSG="$("$VENV_PYTHON" - "$_GW_URL" <<'PYEOF' 2>/dev/null || true
import json, os, sys, urllib.request

gw_url = sys.argv[1]
try:
    from hermit_agent.config import load_settings
except Exception:
    sys.exit(0)

cfg = load_settings(cwd=os.environ.get("PWD"))
model = cfg.get("model", "")
llm_url = cfg.get("llm_url", "")
api_key = cfg.get("llm_api_key", "")

def _suggest_alternatives(current_model: str) -> list[str]:
    """Collect reachable model ids the user could try instead."""
    alts: list[str] = []
    # Locally-installed ollama models.
    try:
        r = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2.0)
        for m in json.loads(r.read()).get("models", []):
            name = m.get("name", "")
            if name and name != current_model:
                alts.append(f"{name}  (local ollama)")
    except Exception:
        pass
    # Models the gateway knows about (includes the configured default
    # for each provider whose key is set elsewhere).
    try:
        r = urllib.request.urlopen(f"{gw_url}/health", timeout=2.0)
        for m in json.loads(r.read()).get("models", []):
            mid = m.get("id", "")
            prov = m.get("provider", "?")
            if mid and mid != current_model:
                alts.append(f"{mid}  (via {prov})")
    except Exception:
        pass
    # De-dup while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for a in alts:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def _emit_alternatives(current_model: str) -> None:
    alts = _suggest_alternatives(current_model)
    if not alts:
        return
    print("\n  Reachable alternatives right now:")
    for a in alts[:10]:
        print(f"    - {a}")
    print(
        "\n  Switch with `export HERMIT_MODEL=<id>` for a one-shot run,"
        "\n  or edit \"model\" in ~/.hermit/settings.json for a persistent change."
    )


gateway_api_key = cfg.get("gateway_api_key", "")

# (a) CLI authenticates against the local gateway. Without
#     gateway_api_key the request is rejected 401 before routing.
if not gateway_api_key or gateway_api_key == "CHANGE_ME_AFTER_FIRST_RUN":
    print(
        "No gateway_api_key in ~/.hermit/settings.json.\n"
        "  Fix: re-run ./install.sh (answer 'Y' to the API key prompt), or mint one manually (docs/cc-setup.md § 2)."
    )
    sys.exit(0)

# (b) Ask the gateway whether it can actually reach the upstream LLM
#     for the requested model. /health reports the aggregated LLM
#     component as 'major' when the configured upstream is down OR
#     when there is no credential for the resolved platform.
try:
    r = urllib.request.urlopen(f"{gw_url}/health", timeout=2.0)
    health = json.loads(r.read())
except Exception:
    # Gateway itself not reachable — the run will fail with a
    # clearer connection error later.
    sys.exit(0)

llm = health.get("components", {}).get("llm", {})
if llm.get("status") == "major":
    err = llm.get("error") or "endpoint unreachable"
    # External model path: if the gateway has no llm_api_key and the
    # requested model routes there, say so plainly instead of hiding
    # behind a generic 'endpoint unreachable'.
    if model and ":" not in model and not api_key:
        print(
            f"Gateway has no upstream credential for external model '{model}'.\n"
            f"  Fix: set \"llm_api_key\" in ~/.hermit/settings.json (this is the gateway's own key for z.ai / external provider),\n"
            f"  or re-run ./install.sh and pick a provider at the prompt."
        )
    else:
        print(
            f"Gateway reports the configured LLM is unreachable:\n"
            f"  url:   {llm.get('url', llm_url)}\n"
            f"  error: {err}\n"
            f"  Fix: check llm_url / llm_api_key (gateway-side) in ~/.hermit/settings.json,\n"
            f"  mount the ollama model storage, or pick a different model."
        )
    _emit_alternatives(model)
PYEOF
)"
  if [ -n "$_PF_MSG" ]; then
    printf '\033[1;31mhermit preflight failed\033[0m\n%s\n' "$_PF_MSG" >&2
    echo "(set HERMIT_SKIP_PREFLIGHT=1 to bypass this check.)" >&2
    exit 2
  fi
fi

# UI location fallback order:
#   1. $HERMIT_UI_DIR (explicit override)
#   2. $HERMIT_DIR/hermit-ui (nested — monorepo layout)
#   3. $HERMIT_DIR/../hermit-ui (sibling — backend/frontend separation)
if [ -n "$HERMIT_UI_DIR" ]; then
  UI_DIR="$HERMIT_UI_DIR"
elif [ -d "$HERMIT_DIR/hermit-ui/dist" ]; then
  UI_DIR="$HERMIT_DIR/hermit-ui"
elif [ -d "$HERMIT_DIR/../hermit-ui/dist" ]; then
  UI_DIR="$HERMIT_DIR/../hermit-ui"
else
  UI_DIR="$HERMIT_DIR/hermit-ui"
fi

# Single-message CLI mode → run Python directly (UI not required).
if [ -n "$1" ] && ! echo "$1" | grep -q "^-"; then
  PYTHONPATH="$HERMIT_DIR:$VENV_SITE" "$VENV_PYTHON" -m hermit_agent "$@"
  exit $?
fi

# Interactive UI mode.
if [ ! -d "$UI_DIR" ]; then
  echo "Hermit UI not found at: $UI_DIR" >&2
  echo "Set HERMIT_UI_DIR to your hermit-ui directory, or run" >&2
  echo "'hermit <message>' for single-message CLI mode." >&2
  exit 1
fi

# Settings: ~/.hermit/settings.json or .hermit/settings.json.
# Override via HERMIT_GATEWAY_URL / HERMIT_GATEWAY_API_KEY.
export PYTHONPATH="$HERMIT_DIR:$VENV_SITE"
# Exported so the UI can locate the backend Python interpreter without
# hardcoding filesystem paths (see hermit-ui/src/app.tsx).
export HERMIT_DIR
export HERMIT_VENV_DIR="$VENV_DIR"
node "$UI_DIR/dist/app.js" "$@"
