#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Listen (System Audio)
# @raycast.mode compact
# @raycast.argument1 { "type": "dropdown", "placeholder": "format", "optional": true, "data": [{"title":"Notion","value":"notion"},{"title":"Obsidian","value":"obsidian"},{"title":"Excalidraw","value":"excalidraw"},{"title":"PNG diagram","value":"png"}] }
# Optional parameters:
# @raycast.icon 🎧
# @raycast.packageName lecnote
# @raycast.description Record what the Mac is playing — YouTube, Zoom — and make notes from it.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# `listen` waits on Enter to stop, which Raycast cannot send, so drive the
# background recorder instead: first run starts it, second run stops and
# transcribes. Same one-key rhythm as the microphone toggle.
exec "$ROOT/bin/lecnote" toggle --source system "${1:-notion}" 2>&1
