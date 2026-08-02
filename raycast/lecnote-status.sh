#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Lecture Notes — Status
# @raycast.mode inline
# Optional parameters:
# @raycast.icon ⏺
# @raycast.packageName lecnote
# @raycast.refreshTime 10s
# @raycast.description Show whether a lecture is currently being recorded.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/lecnote" status 2>&1
