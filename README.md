# VoiceDrop

VoiceDrop is a macOS menu bar recorder and transcription tool for Japanese dictation on Apple Silicon Macs.

## Current Version

- Commit: `37ff9a1`
- Date: `2026-03-25`
- Status: current version

This version can transcribe imported audio files in the background and includes freeze hardening for recording stop.

- Audio files dropped into `Desktop/VoiceDrop Transcripts/Import/Inbox` are picked up automatically.
- Imported files are transcribed in the background while normal live recording can still be started from the menu bar or the Right Option shortcut.
- Imported `wav` files are converted to `mp3` automatically.
- The original `wav` file is deleted only after MP3 conversion is confirmed.
- If conversion fails or the app crashes during processing, the original file is kept.
- Processed imports are written under `Desktop/VoiceDrop Transcripts/Import/Processed`.
- Recording start and stop now run off the main UI thread.
- Repeated shortcut presses during start or stop are ignored to avoid transition races.
- If stopping a recording gets stuck for too long, VoiceDrop exits and relaunches automatically through `launchd`.

## Previous Stable Version

- Commit: `05e1728`
- Date: `2026-03-24`
- Status: last stable version before background import processing

This is the final stable version before the background import queue was added.

- Live recording works from the menu bar and Right Option toggle shortcut.
- Recordings are saved safely in rolling chunks so partial audio can survive a crash.
- Finished recordings are archived as MP3.
- Transcripts are saved and pasted automatically.

## Notes

- The current production code is `voicedrop.py`.
- The desktop launcher starts the Python app from this repository.
