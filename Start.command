#!/bin/bash
cd "$(dirname "$0")"

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$HOME/Library/Application Support/VoiceDrop/voicedrop.pid"
AGENT_LABEL="com.voicedrop.agent"
AGENT_PATH="$HOME/Library/LaunchAgents/com.voicedrop.agent.plist"
GUI_DOMAIN="gui/$(id -u)"

echo ""
echo "================================================"
echo "  🎙️  VoiceDrop 起動"
echo "================================================"
echo ""

# すでに起動中なら終了
if [ -f "$PID_FILE" ]; then
  PID="$(tr -d '[:space:]' < "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    echo "✅ すでに起動中です (PID: $PID)"
    echo ""
    echo "  Enter キーを押すと閉じます"
    read -r
    exit 0
  fi
  rm -f "$PID_FILE"
fi

# launch_voicedrop.sh 経由で起動
bash "$APP_DIR/launch_voicedrop.sh"
EXIT_CODE=$?

sleep 2

if [ $EXIT_CODE -eq 0 ] || pgrep -f "voicedrop.py" >/dev/null 2>&1; then
  echo "✅ 起動しました — メニューバーに 🎙️ が表示されます"
else
  echo "❌ 起動に失敗しました"
  echo "   Debug.command を実行して原因を確認してください"
fi

echo ""
echo "================================================"
echo "  Enter キーを押すと閉じます"
echo "================================================"
read -r
