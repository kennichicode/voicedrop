#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "================================================"
echo "  🔍  VoiceDrop Private Debug"
echo "================================================"
echo ""

# --- Python venv ---
if [ -x "venv/bin/python3" ]; then
  echo "✅ venv/bin/python3: $(venv/bin/python3 --version)"
else
  echo "❌ venv が見つかりません → Install.command を再実行してください"
fi

# --- voicedrop.py ---
if [ -f "voicedrop.py" ]; then
  echo "✅ voicedrop.py 存在"
else
  echo "❌ voicedrop.py が見つかりません"
fi

# --- ffmpeg ---
if command -v ffmpeg >/dev/null 2>&1; then
  echo "✅ ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
  echo "❌ ffmpeg が見つかりません"
fi

# --- Pythonパッケージ確認 ---
echo ""
echo "📦 インストール済みパッケージ:"
venv/bin/pip list 2>/dev/null | grep -E "rumps|sounddevice|numpy|scipy|mlx|faster|pyobjc|pyaudio" || echo "  (取得失敗)"

# --- ログ確認 ---
echo ""
echo "📋 起動ログ (最新10行):"
LOG="$HOME/Library/Logs/VoiceDrop Private/voicedrop-private.log"
LAUNCHER_LOG="$HOME/Library/Logs/VoiceDrop Private/launcher.log"
RESOURCE_LOG="$HOME/Library/Logs/VoiceDrop Private/resource.log"
if [ -f "$LAUNCHER_LOG" ]; then
  echo "--- launcher.log ---"
  tail -10 "$LAUNCHER_LOG"
fi
if [ -f "$LOG" ]; then
  echo "--- voicedrop-private.log ---"
  tail -10 "$LOG"
else
  echo "  (ログファイルなし)"
fi
if [ -f "$RESOURCE_LOG" ]; then
  echo "--- resource.log ---"
  tail -12 "$RESOURCE_LOG"
fi

# --- 現在の使用量 ---
echo ""
echo "📈 現在の使用量:"
PID_FILE="$HOME/Library/Application Support/VoiceDrop Private/voicedrop-private.pid"
if [ -f "$PID_FILE" ]; then
  PID="$(tr -d '[:space:]' < "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    ps -o pid=,etime=,%cpu=,%mem=,rss=,vsz=,command= -p "$PID"
  else
    echo "  (PIDファイルはあるがプロセスは停止中)"
  fi
else
  echo "  (VoiceDrop Privateは未起動)"
fi

# --- 直接起動テスト ---
echo ""
echo "🚀 直接起動テスト (エラーがあればここに表示されます):"
venv/bin/python3 voicedrop.py 2>&1 &
PY_PID=$!
sleep 4
if kill -0 $PY_PID 2>/dev/null; then
  echo "✅ 起動成功（PID: $PY_PID）— このウィンドウを閉じてもアプリは動き続けます"
else
  echo "❌ 起動失敗"
fi

echo ""
echo "================================================"
echo "  Enter キーを押すと閉じます"
echo "================================================"
read -r
