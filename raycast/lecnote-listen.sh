#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Listen (System Audio)
# @raycast.mode compact
# Optional parameters:
# @raycast.icon 🎧
# @raycast.packageName lecnote
# @raycast.description Record what the Mac is playing — YouTube, Zoom — and make Notion notes.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# `listen` waits on Enter to stop, which Raycast cannot send, so drive the
# background recorder instead: first run starts it, second run stops and
# transcribes. Same one-key rhythm as the microphone toggle.
# Always Notion — `lecnote redo <mode>` covers the other formats afterwards.
exec "$ROOT/bin/lecnote" toggle --source system notion 2>&1
