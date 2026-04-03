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

### Transcribe an audio file

Drop an audio file into this folder:

```
Desktop/VoiceDrop Transcripts/Import/Inbox/
```

Supported formats: `.mp3` `.wav` `.m4a` `.aac` `.flac` `.ogg`

Output is saved to:

```
Desktop/VoiceDrop Transcripts/Import/Processed/(date)/
  ├── transcript.txt
  ├── audio.mp3
  └── meta.json
```

### Auto-import iPhone Voice Memos

VoiceDrop can also watch Apple Voice Memos directly here:

```
~/Library/Group Containers/group.com.apple.VoiceMemos.shared
```

Behavior:

- On the first successful scan, existing memos are only registered as a baseline.
- New iPhone Voice Memos are copied into VoiceDrop automatically.
- Transcripts are written into Obsidian Inbox:

```
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault/01_Inbox/
```

- Short memos of 1 minute or less are appended into a daily note such as:

```
01_Inbox/iPhone Voice Memos YYYY-MM-DD.md
```

macOS Full Disk Access is required for VoiceDrop (or Python) to read the protected Voice Memos folder.

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
| Open Transcripts Folder | Open the transcripts folder |
| Model | Switch Whisper model (see below) |
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

### v1.1.0 (2026-03-31)
- **Reduced memory usage**: Default model switched from `whisper-large-v3-turbo` (~1.5GB) to `whisper-small-mlx` (~300MB) — roughly 1/4 the memory footprint
- **Model switcher**: Switch between Small and Large v3 Turbo from the menu bar. Switching restarts the process so memory is fully released

### v1.0.0
- Initial release
