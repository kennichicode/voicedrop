# VoiceDrop

VoiceDrop is a macOS menu bar recorder and transcription tool for Japanese dictation on Apple Silicon Macs.

## Current Version

- Date: `2026-03-25`
- Status: current version

Added dual-inbox support: audio dropped into Obsidian's `01_Inbox` is now transcribed automatically alongside the existing Desktop inbox.

### Dual Inbox

**Desktop Inbox** (unchanged):
- Drop audio into `Desktop/VoiceDrop Transcripts/Import/Inbox/`
- Transcript (`.txt`), archived audio (`.mp3`), and `meta.json` are written to `Desktop/VoiceDrop Transcripts/Import/Processed/{folder}/`

**Obsidian Inbox** (new):
- Drop audio into the Obsidian Vault `01_Inbox/` (works from iPhone via iCloud)
- Transcript is written directly into `01_Inbox/` as a `.md` file
- Audio is archived to `Desktop/VoiceDrop Transcripts/Import/Processed/` as MP3
- Menu bar includes "Open Obsidian Inbox" shortcut

Both inboxes are scanned every 3 seconds. Files are only picked up once stable (unchanged for 2 seconds) to avoid partial reads from iCloud sync.

### Previous features (retained)

- Audio files dropped into `Desktop/VoiceDrop Transcripts/Import/Inbox` are picked up automatically.
- Imported files are transcribed in the background while normal live recording can still be started from the menu bar or the Right Option shortcut.
- Imported `wav` files are converted to `mp3` automatically.
- The original `wav` file is deleted only after MP3 conversion is confirmed.
- If conversion fails or the app crashes during processing, the original file is kept.
- Recording start and stop now run off the main UI thread.
- Repeated shortcut presses during start or stop are ignored to avoid transition races.
- If stopping a recording gets stuck for too long, VoiceDrop exits and relaunches automatically through `launchd`.

## Previous Stable Version

- Commit: `37ff9a1`
- Date: `2026-03-25`
- Status: last stable version before Obsidian inbox support

This is the final stable version before the background import queue was added.

- Live recording works from the menu bar and Right Option toggle shortcut.
- Recordings are saved safely in rolling chunks so partial audio can survive a crash.
- Finished recordings are archived as MP3.
- Transcripts are saved and pasted automatically.

## Notes

- The current production code is `voicedrop.py`.
- The desktop launcher starts the Python app from this repository.
