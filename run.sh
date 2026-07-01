#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
VENV_DIR="$REPO_ROOT/.venv"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Check if python3 is available and working
if ! command -v python3 &>/dev/null || ! python3 -c "import sys" &>/dev/null; then
    echo "========================================================================="
    echo "❌ Python 3 is not installed or not working on your system."
    echo "Please install macOS Command Line Tools by running the following command:"
    echo ""
    echo "    xcode-select --install"
    echo ""
    echo "Or download Python 3.10+ from https://www.python.org/downloads/"
    echo "========================================================================="
    exit 1
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Geocentric launcher"
    echo "Usage: geocentric [--help]"
    echo "Run from any directory to start the local CLI experience."
    exit 0
fi

# Ensure virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Check if dependencies need installation/update
INSTALL_DEPS=0
if [ ! -f "$VENV_DIR/.dependencies_installed" ] || [ "$REPO_ROOT/requirements.txt" -nt "$VENV_DIR/.dependencies_installed" ]; then
    INSTALL_DEPS=1
fi

# Verify if torch is actually importable in the virtual environment
if ! "$VENV_DIR/bin/python" -c "import torch" &>/dev/null; then
    echo "Torch not found or import failed, triggering dependency installation..."
    INSTALL_DEPS=1
fi

if [ "$INSTALL_DEPS" -eq 1 ]; then
    echo "Installing/updating dependencies from requirements.txt..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REPO_ROOT/requirements.txt"
    touch "$VENV_DIR/.dependencies_installed"
fi

echo "========================================================================="
echo "  Geocentric Code"
echo "========================================================================="
echo "  [1] GUI     — Start server and open the web app (default)"
echo "  [2] CLI     — Geocentric Code terminal agent (local models)"
echo "  [3] Connect — CLI to a remote Geocentric host over WiFi"
echo "  [4] Remote  — Show SSH + LAN connection instructions"
echo "========================================================================="
read -r -p "Choose mode [1]: " LAUNCH_MODE
LAUNCH_MODE="${LAUNCH_MODE:-1}"

PORT="${GEOCENTRIC_PORT:-8000}"
HOST="${GEOCENTRIC_HOST:-0.0.0.0}"
PY="$VENV_DIR/bin/python"
export GEOCENTRIC_SUPPRESS_STREAM=1

get_lan_ip() {
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "YOUR-LAN-IP"
}

start_server_background() {
    mkdir -p "$REPO_ROOT/.geocentric"
    echo "Starting Geocentric server on http://${HOST}:${PORT} ..."
    echo "  (server log: $REPO_ROOT/.geocentric/server.log)"
    $PY -m geocentric.cli serve --non-interactive --host "$HOST" --port "$PORT" \
        >> "$REPO_ROOT/.geocentric/server.log" 2>&1 &
    SERVER_PID=$!
    for _ in $(seq 1 30); do
        if curl -sf "http://127.0.0.1:${PORT}/api/status" >/dev/null 2>&1 || curl -sf "http://127.0.0.1:${PORT}/api/v1/models" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "Server did not become ready in time."
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
}

stop_server_background() {
    if [ -n "${SERVER_PID:-}" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}

case "$LAUNCH_MODE" in
    2|cli|CLI)
        echo "========================================================================="
        echo "  Geocentric Code CLI (local, in-process — no server needed)"
        echo "========================================================================="
        $PY -W ignore::Warning -m geocentric.cli interactive
        ;;
    3|connect|Connect)
        read -r -p "Remote server URL (e.g. http://192.168.1.30:${PORT}): " REMOTE_SERVER
        REMOTE_SERVER="${REMOTE_SERVER:-http://127.0.0.1:${PORT}}"
        echo "========================================================================="
        echo "  Connecting Geocentric Code CLI → ${REMOTE_SERVER}"
        echo "  (No local install — downloads thin client from server)"
        echo "========================================================================="
        CLIENT_TMP="$(mktemp /tmp/geocentric-code.XXXXXX.py 2>/dev/null || mktemp 2>/dev/null || echo /tmp/geocentric-code-client.py)"
        curl -sf "${REMOTE_SERVER}/api/cli/client" -o "${CLIENT_TMP}"
        python3 "${CLIENT_TMP}" --server "${REMOTE_SERVER}"
        rm -f "${CLIENT_TMP}"
        ;;
    4|remote|Remote)
        $PY -m geocentric.cli remote --port "$PORT"
        ;;
    *)
        echo "========================================================================="
        echo "  Starting Geocentric GUI on http://localhost:${PORT}"
        LAN_IP="$(get_lan_ip)"
        echo "  Remote CLI:  curl -s http://${LAN_IP}:${PORT}/api/cli/client | python3 - --server http://${LAN_IP}:${PORT}"
        echo "  SSH:         ssh $(whoami)@${LAN_IP}"
        echo "========================================================================="
        $PY -m geocentric.cli serve --non-interactive --host "$HOST" --port "$PORT"
        ;;
esac
