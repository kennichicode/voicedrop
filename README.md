# VoiceDrop Private

A macOS menu bar app for speech transcription — optimized for personal workflows with Obsidian.
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

Move the `voicedrop` folder to where you want to keep it (e.g. `~/Documents`).

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

A `VoiceDrop Private.command` launcher is automatically created on your **Desktop**.

---

## Full Disk Access (required for iPhone Voice Memos)

To enable automatic iPhone Voice Memos transcription, grant Full Disk Access to Terminal:

1. System Settings → Privacy & Security → Full Disk Access
2. Enable **Terminal**

Then always launch VoiceDrop Private by double-clicking `VoiceDrop Private.command` (which opens in Terminal).

---

## Launching

Double-click **`VoiceDrop Private.command`** on your Desktop.
A Terminal window opens and a **VDP** icon appears in your menu bar.

> On first launch, the Whisper model (~300MB) downloads automatically.

---

## Features

### Live recording

| Action | How |
|---|---|
| Start recording | Press **Right Option key** (or menu bar → Start Recording) |
| Stop recording | Press **Right Option key** again |
| Result | Transcript is copied to clipboard and pasted automatically |

Each live recording is saved as its own transcript file in `Desktop/VoiceDrop Private Transcripts/`.

### iPhone Voice Memos — automatic transcription

When Full Disk Access is enabled (see above), VoiceDrop Private automatically watches for new iPhone Voice Memos synced via iCloud.

- New recordings are detected within 3 seconds of syncing
- Short memos (≤60 seconds) are bundled into a daily note: `Vault/01_Inbox/iPhone Voice Memos YYYY-MM-DD.md`
- Long memos (>60 seconds) are saved as individual notes in `Vault/01_Inbox/`
- Existing memos at startup are skipped — only new recordings are processed

**Live recording always takes priority.** If a Voice Memo is being transcribed when you start a live recording, the import is paused and re-queued automatically after the live transcript completes.

### Obsidian inbox — audio file transcription

Drop any audio file into Obsidian's `01_Inbox` folder and it will be automatically transcribed to a `.md` note in the same folder.

Supported formats: `.mp3` `.wav` `.m4a` `.aac` `.flac` `.caf` `.aiff`

---

## Menu reference

| Item | Description |
|---|---|
| Start / Stop Recording | Live recording controls |
| Queue: idle / processing | Shows current transcription status |
| Open Import Inbox | Open the manual import drop folder |
| Open Obsidian Inbox | Open Obsidian's 01_Inbox in Finder |
| Open Imported Jobs | Browse completed import transcripts |
| Shortcut: Right Option | Shows shortcut permission status |
| Open Transcripts Folder | Open all saved transcripts |
| Copy Last Transcript | Copy the last transcript to clipboard |
| Model | Switch Whisper model |
| Quit | Quit VoiceDrop Private |

### Switching models

| Model | Memory | Notes |
|---|---|---|
| ✓ Small (~300MB, faster) | ~300MB | Default |
| Large v3 Turbo (~1.5GB, best accuracy) | ~1.5GB | Best for long recordings |

---

## Troubleshooting

**Install.command won't open**
→ Use **right-click → Open** instead of double-clicking.

**VoiceDrop Private doesn't launch**
→ Re-run `Install.command` to recreate the Desktop launcher.
→ Make sure you haven't moved the folder since installing.

**Right Option key doesn't respond**
→ System Settings → Privacy & Security → Accessibility → enable Python or VoiceDrop Private.

**iPhone Voice Memos not being transcribed**
→ Make sure Terminal has Full Disk Access (see above).
→ Always launch via `VoiceDrop Private.command`, not directly from the folder.

**Transcription spinner stuck**
→ The menu bar shows `TX|` / `TX/` / `TX-` / `TX\` while processing. This is normal for long files.

---

## Changelog

### v2.1.0 (2026-04-03)
- **Live recording preempts imports**: Starting a live recording immediately interrupts any in-progress iPhone/Obsidian transcription; the interrupted job is re-queued and resumes after the live transcript completes
- **Direct Terminal launch**: Removed LaunchAgent dependency — VoiceDrop Private now runs as a Terminal child process, inheriting Full Disk Access automatically
- **iPhone Voice Memos auto-transcription**: New recordings detected within 3 seconds of iCloud sync; short memos bundled into daily Obsidian notes

### v2.0.0 (2026-03-31)
- **Reduced memory usage**: Default model switched to `whisper-small-mlx` (~300MB)
- **Model switcher**: Switch between Small and Large v3 Turbo from the menu bar

### v1.0.0
- Initial private release
