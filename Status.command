#!/bin/bash
cd "$(dirname "$0")"

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$HOME/Library/Application Support/VoiceDrop Private/voicedrop-private.pid"
LOG_FILE="$HOME/Library/Logs/VoiceDrop Private/voicedrop-private.log"
RESOURCE_LOG_FILE="$HOME/Library/Logs/VoiceDrop Private/resource.log"
AGENT_LABEL="com.voicedrop.private.agent"
GUI_DOMAIN="gui/$(id -u)"

echo ""
echo "================================================"
echo "  📊  VoiceDrop Private Status"
echo "================================================"
echo ""

# --- プロセス確認 ---
if [ -f "$PID_FILE" ]; then
  PID="$(tr -d '[:space:]' < "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    echo "✅ 実行中 (PID: $PID)"
    echo "   使用量:"
    ps -o pid=,etime=,%cpu=,%mem=,rss=,vsz=,command= -p "$PID"
  else
    echo "❌ 停止中 (PIDファイルあり・プロセスなし)"
  fi
else
  if pgrep -f "voicedrop.py" >/dev/null 2>&1; then
    echo "✅ 実行中 (PIDファイルなし)"
  else
    echo "❌ 停止中"
  fi
fi

# --- LaunchAgent 状態 ---
echo ""
echo "🔧 LaunchAgent:"
if launchctl print "$GUI_DOMAIN/$AGENT_LABEL" >/dev/null 2>&1; then
  STATE="$(launchctl print "$GUI_DOMAIN/$AGENT_LABEL" 2>/dev/null | grep 'state =' | awk '{print $3}')"
  echo "  登録済み — state: ${STATE:-unknown}"
else
  echo "  未登録"
fi

# --- ログ最新5行 ---
echo ""
echo "📋 直近ログ:"
if [ -f "$LOG_FILE" ]; then
  tail -5 "$LOG_FILE"
else
  echo "  (ログなし)"
fi

echo ""
echo "📈 リソースログ:"
if [ -f "$RESOURCE_LOG_FILE" ]; then
  tail -8 "$RESOURCE_LOG_FILE"
else
  echo "  (resource.log なし)"
fi

echo ""
echo "================================================"
echo "  Enter キーを押すと閉じます"
echo "================================================"
read -r
