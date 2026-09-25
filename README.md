# lecnote

Record a lecture, get clean pastable notes on the clipboard.

Built for one specific failure: the teacher explains a multi-step calculation,
writes a value on the board, then erases and overwrites it while you are still
writing down the previous step. You end up with the superseded number.

`lecnote` records the audio, transcribes the Hinglish, and has Claude resolve
those corrections — keeping only the final values — before putting formatted
notes on your clipboard.

## Install

```bash
pip install git+https://github.com/AASHPAW1015/lecnotes.git
```

That puts `lecnote`, `lecnote-notion`, `lecnote-obsidian` and
`lecnote-excalidraw` on your PATH. Or work from a clone:

```bash
git clone https://github.com/AASHPAW1015/lecnotes.git && cd lecnotes
python3 -m venv .venv
.venv/bin/pip install -e .
export PATH="$PWD/bin:$PATH"      # bin/lecnote runs without activating the venv
```

Requires Python 3.10+ and macOS (the clipboard and notification steps use
`pbcopy` and `osascript`).

## Keys

One key is mandatory. Put it in `~/.lecnote/.env`, which works no matter how you
installed:

```bash
mkdir -p ~/.lecnote
echo 'GROQ_API_KEY=gsk_...' >> ~/.lecnote/.env
```

**`GROQ_API_KEY` is required, always.** Transcription uses Groq's hosted Whisper
large-v3, and **no chat subscription covers speech-to-text** — not Claude Pro,
not ChatGPT Plus, not Google AI Pro. None of them expose an audio endpoint. The
free tier is generous and covers ordinary lecture use. Get one at
https://console.groq.com/keys.

For the notes step you have a choice, and **the options bill from different
pools**:

| `LECNOTE_BACKEND` | Uses | Needs |
|---|---|---|
| `api` | `api.anthropic.com` | prepaid Anthropic API credits |
| `cli` | a vendor's coding CLI, headless | a chat subscription |
| `auto` (default) | api, falling back to cli | either |

A Claude Pro/Max subscription does **not** fund the API — that is a separate
prepaid balance, which is why a perfectly valid `ANTHROPIC_API_KEY` can still
return *"credit balance is too low"*. If you have a subscription and no API
credits, you need no `ANTHROPIC_API_KEY` at all. `auto` handles the fallback.

### Using a subscription you already pay for

The `cli` backend drives a coding CLI in headless mode, so the notes are billed
to that subscription instead of an API balance. Three are wired up:

| `LECNOTE_CLI` | Install | Billed to |
|---|---|---|
| `claude` (default) | https://claude.com/claude-code | Claude Pro / Max |
| `codex` | `npm i -g @openai/codex`, then `codex login` | ChatGPT Plus / Pro |
| `gemini` | `npm i -g @google/gemini-cli`, then run `gemini` once | Google AI Pro / free tier |

```bash
echo 'LECNOTE_BACKEND=cli' >> ~/.lecnote/.env
echo 'LECNOTE_CLI=codex'   >> ~/.lecnote/.env
```

Sign in to the CLI once in a terminal; `lecnote` reuses that login and drops any
conflicting API key from the child process, since an API key in the environment
would otherwise take precedence over the subscription and bill the wrong pool.
Each CLI's own default model is used unless you set `LECNOTE_MODEL`.

So a Groq key plus any one of those subscriptions runs the whole tool with no
per-lecture API spend.

> The `codex` and `gemini` adapters are written to those CLIs' documented
> headless flags but have not been exercised here — only `claude` has been run
> end to end. If a vendor changes its flags, the fix is one entry in
> `CLI_BACKENDS` in `lecnote/notes.py`.

Then check the mic. `doctor` records a few seconds and transcribes it back, so
you can confirm speech-to-text is actually reading your Hinglish before
trusting it with a lecture.

```bash
./bin/lecnote doctor          # -s 10 for longer, -d N for a specific input
```

macOS will not prompt for microphone access on its own here; if this reports
silence, grant your terminal access under
**System Settings > Privacy & Security > Microphone** and fully restart it.

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

### Lectures that are not in a room

`listen` records what the Mac is playing instead of the microphone — a lecture
on YouTube, a Zoom call, a recording a friend sent you:

```bash
lecnote listen            # Enter to stop; notes -> clipboard, same as always
lecnote redo excalidraw   # and re-render it like any other session
```

macOS hands no app the speaker mix, so this needs a virtual device the sound is
routed through first:

```bash
brew install blackhole-2ch
sudo killall coreaudiod     # new audio drivers only appear after this
```

Then in **Audio MIDI Setup**: `+` > *Create Multi-Output Device*, tick **both**
`BlackHole 2ch` and your speakers, and select it as the system output. Ticking
your speakers is what lets you still hear the lecture while it is captured.

```bash
lecnote audio-setup       # says what is installed and what is still missing
```

While that Multi-Output Device is selected the volume keys stop working — a
Core Audio limitation, not something lecnote can fix. So switching back is one
command, and it remembers the real device you were on:

```bash
brew install switchaudio-osx
lecnote output            # capture <-> normal
lecnote output --show     # which one am I on?
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

**One flowchart per procedure.** A lecture that explains DHCP theory, then works
through an IP range, then works out a CIDR value contains two procedures, so
`png` produces two images and `excalidraw` produces one scene holding both
flowcharts side by side. Either way a single paste delivers all of them — the
PNGs go on the pasteboard as file URLs, which is the only way macOS lets
several images paste at once (the image pasteboard holds exactly one picture).
That needs the real `NSPasteboard` API via pyobjc, installed with the other
dependencies; without it the paste falls back to a Finder-only format and says
so. Theory that is not a worked procedure does not become its
own diagram.

Images are written as 128-colour PNGs. A flowchart is flat fills and text, so
the palette is visually identical to full colour at roughly half the size,
which matters once one lecture yields three of them.

Re-render a lecture in another format, without re-recording or paying to
transcribe again — the transcript is already saved, so this is one model call:

```bash
lecnote sessions                    # list what has been captured, numbered
lecnote redo excalidraw             # most recent lecture
lecnote redo png --session 3        # an older one, by number or name prefix
```

One recording can therefore end up as markdown, an Excalidraw scene and a PNG
sitting in the same folder.

Other commands:

```bash
lecnote file lecture.m4a        # process an existing recording
lecnote text transcript.txt     # notes from a transcript you already have
lecnote transcript --session 3  # print a raw transcript
lecnote devices                 # list audio inputs
lecnote clean                   # delete old session folders (keeps 3 newest)
```

`clean` deletes transcripts, so a lecture you want to keep re-renderable needs
`--keep N` or a copy elsewhere.

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

Raycast > Extensions > Script Commands > **Add Script Directory**, pointed at the
`raycast/` folder in this repo. Five commands appear:

| Command | Does |
|---|---|
| Toggle (Notion) | Start recording; run again to stop and copy notes |
| Toggle (Excalidraw) | Same, as a diagram scene |
| Listen (System Audio) | Same rhythm, but records what the Mac is playing |
| Toggle Audio Output | Capture routing ↔ normal sound |
| Re-render | A captured lecture in another format |
| Sessions | List captured lectures |
| Status | Recording, processing (and which stage), or idle — processing lasts until the notes are on the clipboard |

Give *Toggle (Notion)* a hotkey such as ⌥⌘L. One press starts recording, the
next stops it and puts the notes on your clipboard — that single key is the
whole tool during a lecture.

The scripts locate the repo themselves, so nothing needs editing. Raycast needs
its own microphone permission the first time — if a run reports silence, allow
Raycast under **System Settings > Privacy & Security > Microphone**.

Raycast launches scripts with a minimal environment rather than a login shell,
which would otherwise leave the notes CLI unfindable on `PATH` and unable to
locate its login. `lecnote` repairs that itself at startup, so this works from
Raycast, Finder, launchd and cron without a wrapper.

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
`LECNOTE_MODEL`, or switch vendors entirely with `LECNOTE_CLI`; the prompts are
plain text with no Claude-specific syntax, so they port.

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

Verified end to end on real lectures: recording (foreground and background),
compression, chunking, Groq transcription, all four output modes, clipboard,
session management, re-rendering old sessions, the diagram compiler, and the
Raycast hotkey path from a stripped environment.

`test/acceptance.sh` passes 10/10 on repeat runs — all three planted
self-corrections are resolved and none of them are narrated.

Not verified: the `codex` and `gemini` note backends, which are written to those
CLIs' documented headless interfaces but have not been run here.
