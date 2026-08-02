#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Toggle (Notion)
# @raycast.mode compact
# Optional parameters:
# @raycast.icon 🎙️
# @raycast.packageName lecnote
# @raycast.description Start recording the lecture; run again to stop and copy Notion notes.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/lecnote" toggle notion 2>&1
