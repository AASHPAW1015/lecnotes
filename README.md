# lecnote

Record a lecture, get clean pastable notes on the clipboard.

Built for one specific failure: the teacher explains a multi-step calculation,
writes a value on the board, then erases and overwrites it while you are still
writing down the previous step. You end up with the superseded number.

`lecnote` records the audio, transcribes the Hinglish, and has Claude resolve
those corrections — keeping only the final values — before putting formatted
notes on your clipboard.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # add your two keys
```

`GROQ_API_KEY` is required — Claude has no speech-to-text endpoint, so
transcription uses Groq's hosted Whisper (free tier is generous).
Get one at https://console.groq.com/keys.

For the notes step there are two ways to reach Claude, and **they bill from
different pools**:

| `LECNOTE_BACKEND` | Uses | Needs |
|---|---|---|
| `api` | `api.anthropic.com` | prepaid API credits |
| `cli` | the `claude` command, headless | a Claude Pro/Max subscription |
| `auto` (default) | api, falling back to cli | either |

A Pro/Max subscription does **not** fund the API — that is a separate prepaid
balance, which is why a perfectly valid `ANTHROPIC_API_KEY` can still return
*"credit balance is too low"*. If you have a subscription and no API credits,
you need no `ANTHROPIC_API_KEY` at all; just install Claude Code and log in.
`auto` handles the fallback for you.

Then check the mic. `doctor` records a few seconds and transcribes it back, so
you can confirm speech-to-text is actually reading your Hinglish before
trusting it with a lecture.

```bash
./bin/lecnote doctor          # -s 10 for longer, -d N for a specific input
```

macOS will not prompt for microphone access on its own here; if this reports
silence, grant your terminal access under
**System Settings > Privacy & Security > Microphone** and fully restart it.

Put it on your PATH so it is one word to run:

```bash
echo 'export PATH="'$PWD'/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

## Use

```bash
lecnote-notion                 # record; press Enter to stop; notes -> clipboard
lecnote-excalidraw             # same, but a diagram scene instead
lecnote -v "subnetting, CIDR"  # subject hint — improves accuracy a lot
```

Background mode, for when you want to start recording and get back to writing:

```bash
lecnote start        # returns immediately
lecnote status
lecnote stop         # transcribes, writes notes, copies to clipboard
```

Or one command for both edges, which is what a single hotkey should call:

```bash
lecnote toggle            # starts if idle, stops and makes notes if recording
lecnote toggle png        # ...with the format to produce on stop
```

A macOS notification fires when the notes land on the clipboard, so you do not
have to watch the terminal. Set `LECNOTE_NOTIFY=0` to silence it.

### Output modes

| Mode | Produces | Paste into |
|---|---|---|
| `notion` | Markdown — headings, tables, code blocks, checkboxes | Notion, Obsidian |
| `obsidian` | Same plus LaTeX, callouts, highlights | Obsidian |
| `excalidraw` | An editable diagram scene | Excalidraw canvas |
| `png` | A rendered flowchart **image** | Notion, or anywhere |

`png` is the shortcut when you want a diagram *inside* the note rather than a
separate Excalidraw file — it puts a real image on the pasteboard, so Notion
embeds a picture rather than a filename. Same layout engine as `excalidraw`;
pick `excalidraw` when you still want to edit the shapes afterwards.

Re-render the lecture you just captured in another format, without re-recording
or paying to transcribe again:

```bash
lecnote redo excalidraw
```

Other commands:

```bash
lecnote file lecture.m4a        # process an existing recording
lecnote text transcript.txt     # notes from a transcript you already have
lecnote transcript              # print the last raw transcript
lecnote devices                 # list audio inputs
lecnote clean                   # delete old session folders (keeps 3 newest)
```

Useful flags: `-v/--vocab` subject hint, `-d/--device` input index,
`-p/--show` also print the notes, `--keep` keep the audio file.

## Testing it without a lecture

A fixture transcript is included. It is a realistic Hinglish subnetting lecture
containing three deliberate self-corrections — the teacher says five host bits
then corrects to six, block size 32 then 64, and returns later to amend an
earlier step.

```bash
lecnote text fixtures/subnetting-hinglish.txt notion -p
```

Correct output keeps only `6 host bits`, `block size 64`, and
`255.255.255.192`, with no mention that anything was corrected.

For an end-to-end test, play a lecture on your phone next to the laptop and run
`lecnote start` / `lecnote stop`.

## Hotkey (Raycast)

Raycast > Extensions > Script Commands > **Add Script Directory**, and point it
at the `raycast/` folder in this repo. Four commands appear; give
*Lecture Notes — Toggle (Notion)* a hotkey such as ⌥N. One press starts
recording, the next stops it and copies the notes.

The scripts locate the repo themselves, so nothing needs editing. Raycast needs
its own microphone permission the first time — if a run reports silence, allow
Raycast under **System Settings > Privacy & Security > Microphone**.

## How it works

```
mic ──► WAV (streamed to disk) ──► Ogg Vorbis ──► Whisper large-v3 ──► transcript
                                                                          │
                                        Claude Sonnet + mode prompt ◄──────┘
                                                    │
                            markdown ───────────────┴─────────────── diagram spec
                                │                                          │
                                │                                  layout engine
                                ▼                                          ▼
                          pbcopy ──► Notion / Obsidian          pbcopy ──► Excalidraw
```

Audio is streamed to WAV as it records, so a crash still leaves a usable file,
then compressed once at the end — about 7× smaller, which puts a one-hour
lecture near 17 MB and under the 25 MB upload cap without chunking. Longer
recordings are split automatically, with the tail of each transcript carried
into the next chunk as context so the seam does not lose the thread.

### Model choices

**Whisper large-v3** for speech-to-text, because it handles Hindi/English
code-switching. macOS dictation does not. `LECNOTE_STT_LANG` defaults to `en`,
which makes Whisper transliterate Hindi into Latin script rather than emitting
Devanagari; set it to `hi` to compare on your own audio.

**Claude Sonnet** for the notes. This step is not reformatting — it has to
notice that a number was superseded mid-explanation and drop the earlier one.
Haiku tends to keep both. Opus is not worth the cost here. Override with
`LECNOTE_MODEL`.

### Why the diagram works this way

Claude never emits Excalidraw's own format. It emits a small `{nodes, edges}`
spec, and `lecnote/diagram.py` does layering, placement, sizing, and colours.
Asking a model for x/y coordinates and binding IDs directly produces broken
scenes; this way the model's job is trivial and the output is always valid.

Because layout is shared, `excalidraw.py` and `render.py` are just two backends
over the same positions — an Excalidraw scene and a PNG of one lecture look the
same. Adding another output format means writing one more renderer, not another
prompt.

Node `kind` drives the styling: `start`, `step`, `decision`, `result`,
`formula`, `note`.

## Layout

```
lecnote/
  cli.py          commands, session state
  recorder.py     mic capture, compression, chunking
  recproc.py      detached recorder for background mode
  transcribe.py   Whisper (swappable backend)
  notes.py        Claude call
  prompts.py      correction-resolution rules and per-mode formatting
  diagram.py      shared layout engine (layering, placement, sizing)
  excalidraw.py   layout -> Excalidraw scene
  render.py       layout -> PNG, via Pillow
  notify.py       macOS notifications
```

Sessions are kept in `~/.lecnote/sessions/<timestamp>/` with the transcript and
notes, so nothing is lost if a paste goes wrong.

## Status

Verified end to end: recording (foreground and background), compression,
chunking, Groq transcription, both note modes, clipboard, session management,
and the diagram compiler.

`test/acceptance.sh` passes 10/10 on repeat runs — all three planted
self-corrections are resolved and none of them are narrated.

Not yet verified: the Excalidraw scene passes structural checks (46 elements, no
dangling references) but has not been pasted into the real app. The macOS
trigger layer (Shortcuts / Raycast) is not built.
