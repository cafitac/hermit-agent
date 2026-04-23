#!/usr/bin/env bash
# HermitAgent AI Gateway startup script
# Usage:
#   ./bin/gateway.sh              # foreground (log to terminal)
#   ./bin/gateway.sh --daemon     # background (nohup)
#   ./bin/gateway.sh --stop       # Stop

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Settings (needed up front so --stop/--status work without Python) ──
HOST="${HERMIT_GATEWAY_HOST:-0.0.0.0}"
PORT="${HERMIT_GATEWAY_PORT:-8765}"
LOG_DIR="$HOME/.hermit"
LOG_FILE="$LOG_DIR/gateway.log"
PID_FILE="$LOG_DIR/gateway.pid"

mkdir -p "$LOG_DIR"

port_listeners() {
    lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk '!seen[$0]++'
}

is_dashboard_listener() {
    PID="$1"
    CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    case "$CMD" in
        *agent_learner.cli.main*serve-dashboard-fastapi*|*serve-dashboard-fastapi*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

clear_dashboard_conflicts() {
    FOUND=0
    for PID in $(port_listeners); do
        if ! is_dashboard_listener "$PID"; then
            continue
        fi
        FOUND=1
        echo "Stopping dashboard listener on port $PORT (PID $PID) ..."
        kill "$PID" 2>/dev/null || true
        for _i in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$PID" 2>/dev/null || break
            sleep 0.2
        done
        if kill -0 "$PID" 2>/dev/null; then
            echo "  Dashboard PID $PID did not exit on SIGTERM; sending SIGKILL"
            kill -9 "$PID" 2>/dev/null || true
        fi
    done
    return $FOUND
}

# --stop / --status do not need a working Python install. Handle them
# before the venv discovery so uninstall (which may have already removed
# the venv) can still tell us to stop the daemon.
case "${1:-}" in
    --stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill "$PID" 2>/dev/null; then
                echo "Gateway stopped (PID $PID)"
                rm -f "$PID_FILE"
            else
                echo "Gateway not running (stale PID $PID)"
                rm -f "$PID_FILE"
            fi
        else
            PID=$(ps aux | grep '[h]ermit_agent.gateway' | awk '{print $2}' | head -1)
            if [ -n "$PID" ]; then
                kill "$PID"
                echo "Gateway stopped (PID $PID)"
            else
                echo "Gateway not running"
            fi
        fi
        exit 0
        ;;
    --status)
        curl -s "http://127.0.0.1:$PORT/health" | python3 -m json.tool 2>/dev/null || echo "Gateway not responding"
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
    if [ -x "$candidate" ] && "$candidate" -c "import fastapi, uvicorn" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Cannot find Python with fastapi+uvicorn installed."
    echo "  .venv/bin/python or pip install fastapi uvicorn"
    exit 1
fi

# ── Command handling (start paths only) ──────────────────────────────
case "${1:-}" in
    --daemon)
        clear_dashboard_conflicts || true
        echo "Starting HermitAgent AI Gateway (daemon) on $HOST:$PORT ..."
        echo "  Python: $PYTHON"
        echo "  Log: $LOG_FILE"
        nohup "$PYTHON" -m hermit_agent.gateway >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "  PID: $(cat "$PID_FILE")"
            echo "  Health: http://127.0.0.1:$PORT/health"
            curl -s "http://127.0.0.1:$PORT/health" | python3 -m json.tool 2>/dev/null || true
        else
            echo "  ERROR: Gateway exited immediately. Check log:"
            tail -5 "$LOG_FILE"
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;

    *)
        clear_dashboard_conflicts || true
        echo "Starting HermitAgent AI Gateway on $HOST:$PORT ..."
        echo "  Python: $PYTHON"
        echo "  Log: $LOG_FILE"
        echo "  Health: http://127.0.0.1:$PORT/health"
        echo ""
        exec "$PYTHON" -m hermit_agent.gateway
        ;;
esac
