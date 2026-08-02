#!/bin/bash
# Acceptance test: the fixture lecture contains three deliberate self-corrections.
# Correct notes keep only the final values and never mention that a correction
# happened. Run from the project root.
set -uo pipefail
cd "$(dirname "$0")/.."

./bin/lecnote text fixtures/subnetting-hinglish.txt notion >/dev/null 2>&1
F=$(ls -td "$HOME"/.lecnote/sessions/*/ | head -1)notes-notion.md
[ -f "$F" ] || { echo "FAIL: no notes produced"; exit 1; }

pass=0; fail=0
check() {  # check <description> <expect-present|expect-absent> <regex>
  if grep -qiE "$3" "$F"; then found=present; else found=absent; fi
  if [ "$found" = "${2#expect-}" ]; then echo "  PASS  $1"; pass=$((pass+1))
  else echo "  FAIL  $1 (regex was $found)"; fail=$((fail+1)); fi
}

echo "checking $F"
check "superseded '5 host bits' dropped"      expect-absent  "(^|[^0-9])5[^0-9]{0,3}host bits|five host bits"
check "superseded 'block size 32' dropped"    expect-absent  "block size[^0-9]{0,12}32([^0-9]|$)"
check "corrected 6 host bits kept"            expect-present "host bits.*[^0-9]6([^0-9]|$)|6[^0-9]{0,3}host bits"
check "block size 64 kept"                    expect-present "block size.{0,12}64"
check "final mask kept"                       expect-present "255\.255\.255\.192"
check "4 subnets kept"                        expect-present "2\^2[^0-9]{0,6}4|4 subnets|subnets.*[^0-9]4([^0-9]|$)"
check "62 usable hosts kept"                  expect-present "62"
check "corrections not narrated"              expect-absent  "corrected|correction|galat|initially said|first said|erased"
check "no Hinglish leaked"                    expect-absent  "\b(dekho|matlab|theek hai|samajh|likh|nahi)\b"
check "attendance filler dropped"             expect-absent  "attendance"

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
