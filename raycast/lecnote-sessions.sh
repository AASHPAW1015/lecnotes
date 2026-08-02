#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Sessions
# @raycast.mode fullOutput
# Optional parameters:
# @raycast.icon 📚
# @raycast.packageName lecnote
# @raycast.description List captured lectures, so Re-render can point at an older one.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/lecnote" sessions 2>&1
