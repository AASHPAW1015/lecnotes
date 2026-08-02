#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Re-render
# @raycast.mode compact
# @raycast.argument1 { "type": "dropdown", "placeholder": "format", "data": [{"title":"Notion","value":"notion"},{"title":"Obsidian","value":"obsidian"},{"title":"Excalidraw","value":"excalidraw"},{"title":"PNG diagram","value":"png"}] }
# @raycast.argument2 { "type": "text", "placeholder": "session (blank = latest)", "optional": true }
# Optional parameters:
# @raycast.icon ♻️
# @raycast.packageName lecnote
# @raycast.description Re-render a captured lecture in another format, without re-recording.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Blank second argument means "most recent", so only pass --session when given.
if [ -n "${2:-}" ]; then
  exec "$ROOT/bin/lecnote" redo "$1" --session "$2" 2>&1
fi
exec "$ROOT/bin/lecnote" redo "$1" 2>&1
