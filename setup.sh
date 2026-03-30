#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
PYTHON_FORMULA="python@3.12"

echo ""
echo "================================================"
echo "  VoiceDrop Installer"
echo "================================================"
echo ""

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# --- Homebrew ---
if ! command -v brew >/dev/null 2>&1; then
  echo "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x "/usr/local/bin/brew" ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  echo "OK  Homebrew"
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# --- Python ---
if ! brew list --versions "$PYTHON_FORMULA" >/dev/null 2>&1; then
  echo "Installing Python 3.12..."
  brew install "$PYTHON_FORMULA"
else
  echo "OK  Python 3.12"
fi

BREW_PREFIX="$(brew --prefix "$PYTHON_FORMULA" 2>/dev/null || true)"
PYTHON_BIN=""
if [ -n "$BREW_PREFIX" ] && [ -x "$BREW_PREFIX/bin/python3" ]; then
  PYTHON_BIN="$BREW_PREFIX/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "ERROR: Python3 not found"
  exit 1
fi
echo "OK  $("$PYTHON_BIN" --version)"

# --- ffmpeg ---
if ! brew list --versions ffmpeg >/dev/null 2>&1; then
  echo "Installing ffmpeg..."
  brew install ffmpeg
else
  echo "OK  ffmpeg"
fi

# --- venv ---
if [ ! -d "venv" ]; then
  echo "Creating Python virtual environment..."
  "$PYTHON_BIN" -m venv venv
fi

echo "Installing Python packages..."
venv/bin/pip install --upgrade pip --quiet
venv/bin/pip install -r requirements.txt --quiet

# --- Whisper (Apple Silicon: mlx-whisper / Intel: faster-whisper) ---
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
  echo "Installing mlx-whisper (Apple Silicon)..."
  venv/bin/pip install mlx-whisper --quiet
else
  echo "Installing faster-whisper (Intel Mac)..."
  venv/bin/pip install faster-whisper --quiet
fi

chmod +x launch_voicedrop.sh run.sh start.sh 2>/dev/null || true
chmod +x *.command 2>/dev/null || true
xattr -dr com.apple.quarantine . 2>/dev/null || true

# --- Desktop launcher ---
DESKTOP_LAUNCHER="$HOME/Desktop/VoiceDrop.command"
echo "Creating Desktop launcher..."
cat > "$DESKTOP_LAUNCHER" << SCRIPT
#!/bin/zsh
"$APP_DIR/launch_voicedrop.sh"
SCRIPT
chmod +x "$DESKTOP_LAUNCHER"
xattr -dr com.apple.quarantine "$DESKTOP_LAUNCHER" 2>/dev/null || true

# --- Apply icon to launcher ---
ICON_FILE="$APP_DIR/AppIcon.icns"
if [ -f "$ICON_FILE" ]; then
  venv/bin/python3 - "$DESKTOP_LAUNCHER" "$ICON_FILE" << 'PYEOF'
import sys
from AppKit import NSWorkspace, NSImage
target, icon_path = sys.argv[1], sys.argv[2]
image = NSImage.alloc().initWithContentsOfFile_(icon_path)
NSWorkspace.sharedWorkspace().setIcon_forFile_options_(image, target, 0)
PYEOF
  echo "OK  Icon applied to launcher"
fi

echo ""
echo "================================================"
echo "  Setup complete!"
echo "================================================"
echo ""
echo "Double-click 'VoiceDrop.command' on your Desktop to launch."
echo "The first launch downloads the Whisper model (~300MB)."
echo ""
