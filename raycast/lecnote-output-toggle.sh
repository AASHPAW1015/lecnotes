#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Toggle Audio Output
# @raycast.mode compact
# Optional parameters:
# @raycast.icon 🔊
# @raycast.packageName lecnote
# @raycast.description Switch output between capture routing (for `listen`) and normal sound.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/lecnote" output 2>&1
