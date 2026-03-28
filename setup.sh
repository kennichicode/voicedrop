#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_FORMULA="python@3.12"

echo ""
echo "================================================"
echo "  🎙️  VoiceDrop Installer"
echo "================================================"
echo ""

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# --- Homebrew ---
if ! command -v brew >/dev/null 2>&1; then
  echo "📦 Homebrew をインストール中..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x "/usr/local/bin/brew" ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  echo "✅ Homebrew はすでに入っています"
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# --- Python ---
if ! brew list --versions "$PYTHON_FORMULA" >/dev/null 2>&1; then
  echo "🐍 Python 3.12 をインストール中..."
  brew install "$PYTHON_FORMULA"
else
  echo "✅ Python 3.12 はすでに入っています"
fi

BREW_PREFIX="$(brew --prefix "$PYTHON_FORMULA" 2>/dev/null || true)"
PYTHON_BIN=""
if [ -n "$BREW_PREFIX" ] && [ -x "$BREW_PREFIX/bin/python3" ]; then
  PYTHON_BIN="$BREW_PREFIX/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "❌ Python3 が見つかりませんでした"
  exit 1
fi
echo "✅ Python: $("$PYTHON_BIN" --version)"

# --- ffmpeg (音声変換に使用) ---
if ! brew list --versions ffmpeg >/dev/null 2>&1; then
  echo "🎥 ffmpeg をインストール中..."
  brew install ffmpeg
else
  echo "✅ ffmpeg はすでに入っています"
fi

# --- venv ---
if [ ! -d "venv" ]; then
  echo "📦 Python 仮想環境を作成中..."
  "$PYTHON_BIN" -m venv venv
fi

echo "📦 Python パッケージをインストール中..."
venv/bin/pip install --upgrade pip --quiet
venv/bin/pip install -r requirements.txt --quiet

# --- Whisper (アーキテクチャ別) ---
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
  echo "🤖 mlx-whisper をインストール中（Apple Silicon）..."
  venv/bin/pip install mlx-whisper --quiet
else
  echo "🤖 faster-whisper をインストール中（Intel Mac）..."
  venv/bin/pip install faster-whisper --quiet
fi

chmod +x launch_voicedrop.sh run.sh start.sh
chmod +x *.command 2>/dev/null || true

# Gatekeeper quarantine 除去
xattr -dr com.apple.quarantine . 2>/dev/null || true

# VoiceDrop Launcher.app を作成
if [ -f "launcher.applescript" ]; then
  echo "🔨 VoiceDrop Launcher.app を作成中..."
  osacompile -o "VoiceDrop Launcher.app" launcher.applescript
  echo "✅ VoiceDrop Launcher.app 作成完了"
fi

echo ""
echo "================================================"
echo "  ✅ セットアップ完了"
echo "================================================"
echo ""
echo "「VoiceDrop Launcher.app」をダブルクリックすると起動します。"
echo "初回起動時にWhisperモデル（約1.5GB）をダウンロードします。"
echo ""
