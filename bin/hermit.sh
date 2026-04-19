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

# Auto-start the gateway if it isn't already listening. The standalone
# CLI can run without it, but keeping the gateway warm means that if the
# user hops into a Claude Code session next, MCP/run_task traffic lands
# on something alive. Opt out with HERMIT_AUTO_GATEWAY=0.
if [ "${HERMIT_AUTO_GATEWAY:-1}" != "0" ]; then
  _GW_URL="${HERMIT_GATEWAY_URL:-http://127.0.0.1:8765}"
  if ! curl -sf --max-time 1 "$_GW_URL/health" >/dev/null 2>&1; then
    echo "hermit: gateway not reachable at $_GW_URL — starting daemon..." >&2
    "$HERMIT_DIR/bin/gateway.sh" --daemon >/dev/null 2>&1 || \
      echo "hermit: gateway --daemon failed (see ~/.hermit/gateway.log); continuing anyway." >&2
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
