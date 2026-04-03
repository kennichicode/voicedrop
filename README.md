# VoiceDrop

A macOS menu bar app that transcribes your speech and copies it to the clipboard instantly.
All processing happens locally using Whisper AI — **your audio is never sent to the internet.**

---

## Requirements

| | |
|---|---|
| OS | macOS 12 Monterey or later |
| CPU | Apple Silicon (M1+) recommended — Intel Mac also supported |
| Disk | ~500MB (includes Whisper model) |
| Network | Required for initial install only |

---

## Installation

### 1. Place the folder somewhere permanent

Move the `voicedrop` folder to where you want to keep it (e.g. Documents, home folder).

> ⚠️ **Do not move the folder after installing.** The launcher will break if you do.

### 2. Run Install.command

**Right-click `Install.command` → Open.**

> ⚠️ Double-clicking may only show "Move to Trash". Always use **right-click → Open**.
> ⚠️ If macOS says "developer cannot be verified", click **Open**.

A Terminal window will open and automatically install:

- Homebrew
- Python 3.12
- ffmpeg
- Required Python packages
- Whisper speech recognition (Apple Silicon: mlx-whisper / Intel: faster-whisper)

> ⚠️ You may be asked for your Mac login password.
> ⚠️ First install takes 5–15 minutes.

### 3. Done

When you see **"Setup complete!"**, installation is finished.

A `VoiceDrop.command` launcher with a microphone icon is automatically created on your **Desktop**.

---

## Launching

Double-click **`VoiceDrop.command`** on your Desktop.
A Terminal window flashes briefly, then a 🎙️ icon appears in your menu bar.

> On first launch, the Whisper model (~300MB) downloads automatically. This takes a few seconds.

---

## Usage

### Live recording

| Action | How |
|---|---|
| Start recording | Press **Right Option key** (or menu bar 🎙️ → Start Recording) |
| Stop recording | Press **Right Option key** again |
| Result | Transcript is copied to clipboard automatically |

The menu bar icon changes while recording. Open any text field and press Cmd+V to paste.

---

## Accessibility permission (first launch only)

VoiceDrop needs Accessibility access to detect the Right Option key shortcut.

1. Click **Open System Settings** in the prompt
2. Go to Privacy & Security → Accessibility
3. Enable VoiceDrop (or Python)

---

## Menu reference

| Item | Description |
|---|---|
| Start Recording | Start recording |
| Stop Recording | Stop recording |
| Shortcut: Right Option (toggle) | Shows shortcut status |
| Open Transcripts Folder | Open the saved transcripts folder |
| Copy Last Transcript | Copy the last transcript to clipboard |
| Model | Switch Whisper model (see below) |
| Self Check | Print diagnostics to Terminal |
| Quit | Quit VoiceDrop |

### Switching models

Go to **Model** in the menu bar to choose:

| Model | Memory | Notes |
|---|---|---|
| ✓ Small (~300MB, faster) | ~300MB | Default. Fast, accurate for most use cases |
| Large v3 Turbo (~1.5GB, best accuracy) | ~1.5GB | Best accuracy for long recordings and technical terms |

Switching models restarts VoiceDrop automatically. Both models are never loaded at the same time.

---

## Troubleshooting

**Install.command won't open (only shows "Move to Trash")**
→ Use **right-click → Open** instead of double-clicking.

**VoiceDrop doesn't launch**
→ Re-run `Install.command` to recreate the Desktop launcher.
→ Make sure you haven't moved the `voicedrop` folder since installing.

**Right Option key doesn't respond**
→ Check System Settings → Privacy & Security → Accessibility and make sure VoiceDrop (or Python) is enabled.

**Transcription doesn't start**
→ On first launch, the model is downloading. Wait a few seconds.
→ While downloading, the menu bar shows "Loading...".

**Uninstalling**
→ Drag the `voicedrop` folder to the Trash.
→ Homebrew, Python, and ffmpeg remain (they may be shared with other apps).

---

## Changelog

### v2.0.0 (2026-04-03)
- **Live recording only**: Simplified to focus on the core use case — speak, transcribe, paste
- Removed Import Inbox and Obsidian integration (available in VoiceDrop Private)

### v1.1.0 (2026-03-31)
- **Reduced memory usage**: Default model switched from `whisper-large-v3-turbo` (~1.5GB) to `whisper-small-mlx` (~300MB)
- **Model switcher**: Switch between Small and Large v3 Turbo from the menu bar

### v1.0.0
- Initial release
