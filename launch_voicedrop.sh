#!/bin/zsh

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PYTHON_BIN="$APP_DIR/venv/bin/python3"
SCRIPT_PATH="$APP_DIR/voicedrop.py"
AGENT_SOURCE="$APP_DIR/com.voicedrop.agent.plist"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT_PATH="$AGENT_DIR/com.voicedrop.agent.plist"
AGENT_LABEL="com.voicedrop.agent"
GUI_DOMAIN="gui/$(id -u)"
STATE_DIR="$HOME/Library/Application Support/VoiceDrop"
LOG_DIR="$HOME/Library/Logs/VoiceDrop"
PID_FILE="$STATE_DIR/voicedrop.pid"
BOOT_LOG="$LOG_DIR/launcher.log"

mkdir -p "$STATE_DIR" "$LOG_DIR" "$AGENT_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python: $PYTHON_BIN" >> "$BOOT_LOG"
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Missing script: $SCRIPT_PATH" >> "$BOOT_LOG"
  exit 1
fi

if [[ ! -f "$AGENT_SOURCE" ]]; then
  echo "Missing launch agent template: $AGENT_SOURCE" >> "$BOOT_LOG"
  exit 1
fi

if [[ ! -f "$AGENT_PATH" ]] || ! grep -q "$APP_DIR" "$AGENT_PATH" 2>/dev/null; then
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__HOME__|$HOME|g" "$AGENT_SOURCE" > "$AGENT_PATH"
  launchctl bootout "$GUI_DOMAIN" "$AGENT_PATH" >/dev/null 2>&1 || true
fi

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(tr -d '[:space:]' < "$PID_FILE" || true)"
  if [[ -n "${existing_pid:-}" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    exit 0
  fi
  rm -f "$PID_FILE"
fi

timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
echo "$timestamp launching VoiceDrop" >> "$BOOT_LOG"

if ! launchctl print "$GUI_DOMAIN/$AGENT_LABEL" >/dev/null 2>&1; then
  launchctl bootstrap "$GUI_DOMAIN" "$AGENT_PATH" >> "$BOOT_LOG" 2>&1
fi

launchctl kickstart -k "$GUI_DOMAIN/$AGENT_LABEL" >> "$BOOT_LOG" 2>&1

sleep 2

if [[ -f "$PID_FILE" ]]; then
  started_pid="$(tr -d '[:space:]' < "$PID_FILE" || true)"
  if [[ -n "${started_pid:-}" ]] && kill -0 "$started_pid" 2>/dev/null; then
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if pgrep -f "$SCRIPT_PATH" >/dev/null 2>&1; then
  exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') launcher did not observe pid file" >> "$BOOT_LOG"
exit 1
