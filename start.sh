#!/usr/bin/env bash
# start.sh — dynamic-port dev launcher for ai-hedge-fund
#
# Port assignment: backend=even, frontend=even+1 (odd)
# Discovered ports are persisted to .dev-ports so subsequent runs reuse them.
# Graceful shutdown on SIGINT/SIGTERM with 15 s timeout before SIGKILL.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTS_FILE="$SCRIPT_DIR/.dev-ports"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

BACKEND_PID=""
FRONTEND_PID=""
BACKEND_PORT=""
FRONTEND_PORT=""

is_port_free() {
    ! lsof -iTCP:"$1" -sTCP:LISTEN -t > /dev/null 2>&1
}

kill_port() {
    local port=$1
    local pids
    pids=$(lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        warn "Killing existing process(es) on port $port (PIDs: $pids)"
        # shellcheck disable=SC2086
        kill $pids 2>/dev/null || true
        sleep 1
    fi
}

find_free_port_pair() {
    # Reuse saved ports when both are still free
    if [[ -f "$PORTS_FILE" ]]; then
        local saved_backend="" saved_frontend=""
        # Read only the two variables we expect, ignore anything else
        while IFS='=' read -r key val; do
            [[ "$key" == "SAVED_BACKEND_PORT" ]] && saved_backend="$val"
            [[ "$key" == "SAVED_FRONTEND_PORT" ]] && saved_frontend="$val"
        done < "$PORTS_FILE"

        if [[ -n "$saved_backend" && -n "$saved_frontend" ]]; then
            if is_port_free "$saved_backend" && is_port_free "$saved_frontend"; then
                BACKEND_PORT=$saved_backend
                FRONTEND_PORT=$saved_frontend
                info "Reusing saved ports — backend=$BACKEND_PORT  frontend=$FRONTEND_PORT"
                return 0
            else
                info "Saved ports ($saved_backend/$saved_frontend) are in use — searching for a new pair"
            fi
        fi
    fi

    # Scan for the next free even+odd pair starting from 8000
    for port in $(seq 8000 2 9998); do
        if is_port_free "$port" && is_port_free "$((port + 1))"; then
            BACKEND_PORT=$port
            FRONTEND_PORT=$((port + 1))
            # Persist so the next run reuses this pair
            printf 'SAVED_BACKEND_PORT=%d\nSAVED_FRONTEND_PORT=%d\n' \
                "$BACKEND_PORT" "$FRONTEND_PORT" > "$PORTS_FILE"
            info "Found free port pair — backend=$BACKEND_PORT  frontend=$FRONTEND_PORT (saved to .dev-ports)"
            return 0
        fi
    done

    error "No free even/odd port pair found in range 8000-9999"
    exit 1
}

cleanup() {
    echo ""
    info "Shutting down services (15 s grace period)..."

    [[ -n "$BACKEND_PID" ]]  && kill -TERM "$BACKEND_PID"  2>/dev/null || true
    [[ -n "$FRONTEND_PID" ]] && kill -TERM "$FRONTEND_PID" 2>/dev/null || true

    local deadline=$(( $(date +%s) + 15 ))
    while true; do
        local still_running=0
        [[ -n "$BACKEND_PID" ]]  && kill -0 "$BACKEND_PID"  2>/dev/null && still_running=1 || true
        [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null && still_running=1 || true
        [[ $still_running -eq 0 ]] && break

        if (( $(date +%s) >= deadline )); then
            warn "Grace period expired — force killing"
            [[ -n "$BACKEND_PID" ]]  && kill -KILL "$BACKEND_PID"  2>/dev/null || true
            [[ -n "$FRONTEND_PID" ]] && kill -KILL "$FRONTEND_PID" 2>/dev/null || true
            break
        fi
        sleep 0.5
    done

    ok "Services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# ── discover ports ────────────────────────────────────────────────────────────
find_free_port_pair

# Kill anything already squatting on the chosen ports
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

# ── start backend ─────────────────────────────────────────────────────────────
info "Starting backend on port $BACKEND_PORT..."
CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}" \
    poetry run uvicorn app.backend.main:app \
        --reload --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!

# Wait up to 30 s for backend to become reachable
info "Waiting for backend to be ready..."
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/docs" > /dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        error "Backend process exited unexpectedly"
        exit 1
    fi
    sleep 1
done

# ── start frontend ────────────────────────────────────────────────────────────
info "Starting frontend on port $FRONTEND_PORT..."
(
    cd "$SCRIPT_DIR/app/frontend"
    VITE_API_URL="http://localhost:${BACKEND_PORT}" \
        npx pnpm dev --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo ""
ok "Backend:   http://localhost:${BACKEND_PORT}"
ok "API docs:  http://localhost:${BACKEND_PORT}/docs"
ok "Frontend:  http://localhost:${FRONTEND_PORT}"
echo ""
info "Press Ctrl+C to stop both services"
echo ""

# ── wait for either process to exit ──────────────────────────────────────────
while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        error "Backend exited unexpectedly"
        break
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        error "Frontend exited unexpectedly"
        break
    fi
    sleep 1
done

cleanup
