#!/bin/bash
cd "$(dirname "$0")"

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$HOME/Library/Application Support/VoiceDrop/voicedrop.pid"

# quarantine 除去
xattr -d com.apple.quarantine "$APP_DIR"/*.command 2>/dev/null || true
xattr -d com.apple.quarantine "$APP_DIR"/*.sh 2>/dev/null || true

# すでに起動中なら終了
if [ -f "$PID_FILE" ]; then
  PID="$(tr -d '[:space:]' < "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    echo "✅ すでに起動中です (PID: $PID)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

bash "$APP_DIR/launch_voicedrop.sh"
sleep 2

if pgrep -f "voicedrop.py" >/dev/null 2>&1; then
  echo "✅ 起動しました — メニューバーに 🎙️ が表示されます"
else
  echo "❌ 起動に失敗しました — debug.sh を実行してください"
  exit 1
fi
