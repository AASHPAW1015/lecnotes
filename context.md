# Lecture Notes Tool — Context

## Problem
Lecturer explains multi-step calculations (e.g. subnet mask math) verbally, correcting/overwriting earlier numbers mid-explanation. Writing notes by hand means missing the correction — you're still writing the previous step when the overlapping correction is said, erased, replaced.

Personal, single-user tool. Not building a note-taking app — building a quick capture-and-structure pipeline for moments you can't keep up manually.

## Core flow
1. Run terminal command with a mode suffix, e.g. `note-notion` or `note-excalidraw`.
2. Tool starts listening on mic in background, prints "listening".
3. Stop via second command / hotkey / pause.
4. Audio → transcript (speech-to-text).
5. Transcript + mode-specific prompt → Claude API.
6. Claude output → clipboard (macOS pasteboard).
7. Paste into Notion / Obsidian / Excalidraw — formatted appropriately per target app.

## Key requirements
- Lectures are in Hinglish (Hindi-English code-switched). STT must handle this — Mac's built-in speech recognition is not sufficient.
- LLM step must detect self-corrections in the transcript ("wait no", "galat bola", "actually it's X") and resolve to final correct value, not just transcribe both versions in sequence. This is the actual point of the tool, not just formatting.
- Output must be genuinely pastable in target format:
  - Notion / Obsidian: markdown — bullets, headers, code blocks, checkboxes.
  - Excalidraw: real shapes/arrows, meaning proper `excalidraw/clipboard` JSON scene format (elements array with x/y coords, arrow bindings) — not just text.
- User supplies own Claude API key.
- Testing method: play a YouTube lecture on phone, let mic pick it up, run tool end to end.

## Architecture decision (proposed)
```
terminal cmd (note-notion / note-excalidraw)
  → start mic recording (bg process)
  → stop on second cmd / hotkey
  → audio → transcript (STT)
  → transcript + mode-specific prompt → Claude
  → formatted output → clipboard (pbcopy)
  → paste in target app
```

No real-time streaming transcription needed — record full audio buffer, transcribe once on stop. Simpler than live diarization/streaming.

## Model choices (proposed, not finalized)
- **STT**: Whisper large-v3 for Hinglish handling.
  - Groq API (whisper-large-v3): fast, cheap, no local compute needed. First candidate to try.
  - Local whisper.cpp: free, private, more setup friction, slower depending on hardware.
  - Deepgram nova-2/3: alternative, explicitly trained on code-switched multilingual — worth A/B testing against Whisper on a real Hinglish clip.
- **Note generation**: Claude Sonnet. Task needs reasoning (detect correction, merge steps into clean flow), not just formatting — Haiku likely insufficient for the correction-detection nuance. Opus not needed, cost not justified for this task.

## Build phases (proposed)
1. CLI script (Python likely — simplest for audio capture + clipboard access). Notion/markdown mode only. Test against recorded YouTube lecture audio.
2. Iterate on prompt for correction-merging logic — expected to be the main iteration loop.
3. Excalidraw JSON output mode (harder, separate effort).
4. macOS wrapper — Shortcuts app / Raycast script command / menu bar app — added last, after core logic is proven from terminal.

## Decisions made during the build (2026-08-02)

**Audio capture: `sounddevice` + `soundfile`, not ffmpeg.**
Neither ffmpeg nor sox was installed. Their PyPI wheels bundle PortAudio and
libsndfile, so `pip install` alone gets a working recorder with no Homebrew
dependency. Verified working: 4s capture at peak 0.017, terminal already had
microphone permission.

**Record WAV, compress after.** WAV is streamed to disk during recording so a
crash or hard kill still leaves a playable file. Conversion to Ogg Vorbis
happens once, on stop. Measured 7x compression (200 KB -> 29 KB), which puts a
one-hour lecture near 17 MB — under the 25 MB Whisper upload cap with no
chunking needed. Chunking exists anyway for longer recordings, carrying the tail
of each transcript into the next chunk as Whisper's prompt so the seam keeps
context.

**Stop trigger: both.** Foreground `lecnote` records until Enter. Background
`lecnote start` / `lecnote stop` uses a detached process plus a PID file, which
is what a macOS Shortcut or Raycast command will call later.

**Excalidraw: the model never emits Excalidraw JSON.** It emits a small
`{nodes, edges}` spec; `lecnote/excalidraw.py` does layering (longest-path),
connected-component placement, text wrapping, sizing, colours, and arrow
binding. This was the risk flagged in planning, and this is the mitigation —
the model's job becomes trivial and the output is structurally valid by
construction. Node `kind` (`start`/`step`/`decision`/`result`/`formula`/`note`)
drives styling, so the model never picks coordinates or hex colours.

**Two API keys are required.** Claude has no speech-to-text endpoint, so
transcription needs a separate provider. Groq's hosted whisper-large-v3 is the
default backend; `transcribe.BACKENDS` is the swap point for testing Deepgram.

**Notes backend: `auto` (API, falling back to the `claude` CLI).** Discovered
during testing that a Claude Pro/Max subscription does not fund the Anthropic
API — they are separate billing pools. A valid API key returned
"Your credit balance is too low" while the subscription was active and paid.
So `notes.py` grew a second backend that shells out to `claude -p` in headless
mode, which bills against the subscription instead. It runs with
`--system-prompt` (replacing Claude Code's default), `--disallowed-tools`, and
a temp cwd so no CLAUDE.md or repo context leaks into the notes. One trap: an
`ANTHROPIC_API_KEY` present in the environment takes precedence over the
claude.ai login, so the child process gets it stripped from its env.
This means the tool works with *either* API credits or a subscription.

**`redo` and `text` commands.** Transcripts are cached per session, so
re-rendering a captured lecture in another format costs one Claude call and no
transcription. `lecnote text <file>` skips audio entirely — used to test the
notes half without spending on STT.

## Open questions / unresolved
- Which STT provider wins on real Hinglish audio — still needs an A/B test on a
  real lecture. `transcribe.BACKENDS` is the seam for adding Deepgram.
- `LECNOTE_STT_LANG` defaults to `en` (transliterates Hindi to Latin script)
  versus `hi` (Devanagari) — untested which produces better final notes.
- Excalidraw scene passes structural checks (46 elements, no dangling
  references) but has not been pasted into the real app yet.
- Reference text for "what good notes look like" — user to share; the prompt in
  `prompts.py` is written from the stated requirements only.
- macOS trigger layer not built yet (Shortcuts / Raycast / menu bar).

## Status
Prototype built and working end to end, including both live API calls.

Verified: foreground and background recording, mic permission, compression
ratio, chunking logic, session state, clipboard write, both output modes, and
the diagram compiler (id uniqueness, arrow bindings and `boundElements` all
resolve).

Both live calls now verified. Groq returned an accurate transcript of
synthesized test audio, converting spoken numbers to digits correctly
("two fifty five dot ... one ninety two" -> "255.255.255.192").
`fixtures/subnetting-hinglish.txt` plus `test/acceptance.sh` is the acceptance
test, passing 10/10 on repeat runs: a Hinglish
subnetting lecture with three deliberate self-corrections (five host bits
corrected to six, block size 32 corrected to 64, and a later return to amend an
earlier step). Correct output keeps only `6 host bits`, `block size 64`, and
`255.255.255.192`, with no mention that anything was corrected.
