#!/bin/zsh

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$APP_DIR/venv/bin/python3"
SCRIPT_PATH="$APP_DIR/voicedrop.py"
STATE_DIR="$HOME/Library/Application Support/VoiceDrop Private"
LOG_DIR="$HOME/Library/Logs/VoiceDrop Private"
PID_FILE="$STATE_DIR/voicedrop-private.pid"

mkdir -p "$STATE_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python: $PYTHON_BIN"
  exit 1
fi

# すでに起動中なら終了
if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(tr -d '[:space:]' < "$PID_FILE" || true)"
  if [[ -n "${existing_pid:-}" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "VoiceDrop Private はすでに起動しています (PID: $existing_pid)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

cd "$APP_DIR"
exec "$PYTHON_BIN" "$SCRIPT_PATH"
