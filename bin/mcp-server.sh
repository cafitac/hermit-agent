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

mkdir -p "$LOG_DIR"

# --stop / --status do not need Python. Handle them before venv
# discovery so uninstall (which may have already removed .venv) can
# still stop the daemon.
case "${1:-}" in
    --stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill "$PID" 2>/dev/null; then
                echo "MCP Server stopped (PID $PID)"
                rm -f "$PID_FILE"
            else
                echo "MCP Server not running (stale PID $PID)"
                rm -f "$PID_FILE"
            fi
        else
            PID=$(ps aux | grep '[h]ermit_agent.mcp_server' | awk '{print $2}' | head -1)
            if [ -n "$PID" ]; then
                kill "$PID"
                echo "MCP Server stopped (PID $PID)"
            else
                echo "MCP Server not running"
            fi
        fi
        exit 0
        ;;
    --status)
        echo "=== MCP Server ==="
        ps aux | grep '[h]ermit_agent.mcp_server' | awk '{print "PID:", $2, "started:", $9}' || echo "not running"
        echo ""
        echo "=== Gateway ==="
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
    echo "ERROR: Cannot find Python with the mcp package installed."
    echo "  .venv/bin/python or pip install mcp"
    exit 1
fi

# ── Command handling (start paths only) ──────────────────────────────
case "${1:-}" in
    --http)
        echo "Starting HermitAgent MCP Server (HTTP mode, port $PORT) ..."
        echo "  Python: $PYTHON"
        echo "  Log: $LOG_FILE"
        nohup "$PYTHON" -m hermit_agent.mcp_server --http "$PORT" >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "  PID: $(cat "$PID_FILE")"
            echo "  MCP: http://0.0.0.0:$PORT/mcp"
        else
            echo "  ERROR: MCP Server exited immediately. Check log:"
            tail -5 "$LOG_FILE"
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;

    *)
        echo "Starting HermitAgent MCP Server (stdio mode, Gateway proxy) ..."
        echo "  Python: $PYTHON"
        echo "  Log: $LOG_FILE"
        echo ""
        exec "$PYTHON" -m hermit_agent.mcp_server
        ;;
esac
