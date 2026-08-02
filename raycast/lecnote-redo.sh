#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Re-render Last
# @raycast.mode compact
# @raycast.argument1 { "type": "dropdown", "placeholder": "format", "data": [{"title":"Notion","value":"notion"},{"title":"Obsidian","value":"obsidian"},{"title":"Excalidraw","value":"excalidraw"}] }
# Optional parameters:
# @raycast.icon ♻️
# @raycast.packageName lecnote
# @raycast.description Re-render the last lecture in another format, without re-recording.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/lecnote" redo "$1" 2>&1
