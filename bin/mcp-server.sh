#!/usr/bin/env bash
# HermitAgent MCP Server startup script (Gateway proxy mode)
# Usage:
#   ./bin/mcp-server.sh              # stdio mode (direct Claude Code connection)
#   ./bin/mcp-server.sh --http       # HTTP mode (Docker/LaunchAgent)
#   ./bin/mcp-server.sh --http 3737  # HTTP mode + custom port
#   ./bin/mcp-server.sh --stop       # Stop
#   ./bin/mcp-server.sh --status     # Check status

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Settings (needed up front so --stop/--status work without Python) ──
LOG_DIR="$HOME/.hermit"
LOG_FILE="$LOG_DIR/mcp_server.log"
PID_FILE="$LOG_DIR/mcp_server.pid"
PORT="${2:-3737}"
GATEWAY_URL="${HERMIT_MCP_GATEWAY_URL:-http://127.0.0.1:8765}"
AUTO_GATEWAY="${HERMIT_MCP_AUTO_GATEWAY:-1}"
GATEWAY_WAIT_SEC="${HERMIT_MCP_GATEWAY_WAIT_SEC:-8}"
RESTART_IDLE_GATEWAY="${HERMIT_MCP_RESTART_IDLE_GATEWAY:-0}"

mkdir -p "$LOG_DIR"

gateway_health_check() {
    RESPONSE="$(curl -fsS "$GATEWAY_URL/health" 2>/dev/null || true)"
    [ -n "$RESPONSE" ] || return 1
    printf '%s' "$RESPONSE" \
        | python3 -c "import json,sys; data=json.load(sys.stdin); sys.exit(0 if data.get('service') == 'hermit_agent-gateway' else 1)" \
        >/dev/null 2>&1
}

gateway_active_tasks() {
    curl -fsS "$GATEWAY_URL/health" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('components',{}).get('tasks',{}).get('active_total',0))" 2>/dev/null \
        || echo "0"
}

ensure_gateway() {
    if [ "$AUTO_GATEWAY" = "0" ] || [ "$AUTO_GATEWAY" = "false" ] || [ "$AUTO_GATEWAY" = "no" ]; then
        echo "  Gateway auto-start disabled (HERMIT_MCP_AUTO_GATEWAY=$AUTO_GATEWAY)" >&2
        return 0
    fi

    if gateway_health_check; then
        ACTIVE=$(gateway_active_tasks)
        if [ "$ACTIVE" -gt 0 ] 2>/dev/null; then
            echo "  Gateway: healthy, $ACTIVE active task(s) — skipping restart" >&2
            return 0
        fi
        if [ "$RESTART_IDLE_GATEWAY" = "1" ] || [ "$RESTART_IDLE_GATEWAY" = "true" ] || [ "$RESTART_IDLE_GATEWAY" = "yes" ]; then
            echo "  Gateway: restarting (idle, picking up latest code) ..." >&2
            ./bin/gateway.sh --stop >/dev/null 2>&1 || true
            sleep 1
        else
            echo "  Gateway: healthy and idle — reusing existing process" >&2
            return 0
        fi
    else
        echo "  Gateway: starting automatically ..." >&2
    fi

    ./bin/gateway.sh --daemon >/dev/null 2>&1 || true

    elapsed=0
    while [ "$elapsed" -lt "$GATEWAY_WAIT_SEC" ]; do
        if gateway_health_check; then
            echo "  Gateway: healthy at $GATEWAY_URL" >&2
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    echo "  ERROR: Gateway did not become healthy within ${GATEWAY_WAIT_SEC}s" >&2
    echo "  Check: $HOME/.hermit/gateway.log" >&2
    return 1
}

# --stop / --status do not need Python. Handle them before venv
# discovery so uninstall (which may have already removed .venv) can
# still stop the daemon.
case "${1:-}" in
    --stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill "$PID" 2>/dev/null; then
                echo "MCP Server stopped (PID $PID)" >&2
                rm -f "$PID_FILE"
            else
                echo "MCP Server not running (stale PID $PID)" >&2
                rm -f "$PID_FILE"
            fi
        else
            PID=$(ps aux | grep '[h]ermit_agent.mcp_server' | awk '{print $2}' | head -1)
            if [ -n "$PID" ]; then
                kill "$PID"
                echo "MCP Server stopped (PID $PID)" >&2
            else
                echo "MCP Server not running" >&2
            fi
        fi
        exit 0
        ;;
    --status)
        echo "=== MCP Server ===" >&2
        ps aux | grep '[h]ermit_agent.mcp_server' | awk '{print "PID:", $2, "started:", $9}' || echo "not running"
        echo "" >&2
        echo "=== Gateway ===" >&2
        curl -s "http://127.0.0.1:8765/health" | python3 -m json.tool 2>/dev/null || echo "Gateway not responding"
        exit 0
        ;;
esac

# ── Python path discovery (start paths need this) ─────────────────────
# Override with HERMIT_VENV_DIR if your venv lives outside the project root.
PYTHON=""
for candidate in \
    ".venv/bin/python" \
    "${HERMIT_VENV_DIR:-}/bin/python" \
    "$(which python3 2>/dev/null)" \
    "$(which python 2>/dev/null)"; do
    if [ -x "$candidate" ] && "$candidate" -c "import mcp" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Cannot find Python with the mcp package installed." >&2
    echo "  .venv/bin/python or pip install mcp" >&2
    exit 1
fi

# ── Command handling (start paths only) ──────────────────────────────
case "${1:-}" in
    --http)
        echo "Starting HermitAgent MCP Server (HTTP mode, port $PORT) ..." >&2
        echo "  Python: $PYTHON" >&2
        echo "  Log: $LOG_FILE" >&2
        nohup "$PYTHON" -m hermit_agent.mcp_server --http "$PORT" >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "  PID: $(cat "$PID_FILE")" >&2
            echo "  MCP: http://0.0.0.0:$PORT/mcp" >&2
        else
            echo "  ERROR: MCP Server exited immediately. Check log:" >&2
            tail -5 "$LOG_FILE"
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;

    *)
        echo "Starting HermitAgent MCP Server (stdio mode, Gateway proxy) ..." >&2
        echo "  Python: $PYTHON" >&2
        echo "  Log: $LOG_FILE" >&2
        if ! ensure_gateway; then
            exit 1
        fi
        echo "" >&2
        exec "$PYTHON" -m hermit_agent.mcp_server
        ;;
esac
