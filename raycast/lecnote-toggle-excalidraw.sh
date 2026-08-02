#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Toggle (Excalidraw)
# @raycast.mode compact
# Optional parameters:
# @raycast.icon 🧩
# @raycast.packageName lecnote
# @raycast.description Start recording; run again to stop and copy an Excalidraw diagram.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/lecnote" toggle excalidraw 2>&1
