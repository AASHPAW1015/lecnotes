"""lecnote — record a lecture, get pastable notes on the clipboard.

    lecnote                     record, press Enter to stop, notes -> clipboard
    lecnote-notion              same, Notion markdown (argv[0] picks the mode)
    lecnote start / lecnote stop    background recording
    lecnote redo excalidraw     re-render the last lecture in another format
    lecnote file talk.m4a       process an existing recording
"""

import argparse
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import __version__, clipboard, config, notes, notify, prompts, recorder

MODES = list(prompts.MODES)
DEFAULT_MODE = "notion"


def log(msg: str = "") -> None:
    """Progress goes to stderr so stdout stays pipeable (`lecnote -p > notes.md`)."""
    print(msg, file=sys.stderr, flush=True)


# --- session state --------------------------------------------------------

def _new_session() -> Path:
    config.ensure_dirs()
    path = config.SESSIONS / datetime.now().strftime("%Y%m%d-%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_meta(session: Path, **fields) -> None:
    meta_path = session / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    meta.update(fields)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _read_meta(session: Path) -> dict:
    path = session / "meta.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _set_last(session: Path) -> None:
    (config.HOME / "last.json").write_text(
        json.dumps({"session": str(session)}), encoding="utf-8")


def _last_session() -> Path | None:
    path = config.HOME / "last.json"
    if not path.is_file():
        return None
    session = Path(json.loads(path.read_text())["session"])
    return session if session.is_dir() else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM
    return True


# --- pipeline -------------------------------------------------------------

def _check_audio(wav: Path, session: Path) -> None:
    stats_path = wav.with_suffix(".stats.json")
    peak = None
    if stats_path.is_file():
        peak = json.loads(stats_path.read_text()).get("peak")
    secs = recorder.duration(wav)
    log(f"  captured {secs:.0f}s of audio")
    if secs < 1.0:
        raise SystemExit("error: recording is under a second — nothing to transcribe.")
    if peak is not None and peak < 0.001:
        raise SystemExit(
            "error: the microphone recorded pure silence.\n"
            "  Grant your terminal microphone access:\n"
            "  System Settings > Privacy & Security > Microphone > enable your terminal app,\n"
            "  then fully quit and reopen it. Verify with `lecnote doctor`.")
    _write_meta(session, seconds=secs, peak=peak)


def _process(session: Path, mode: str, vocab: str, show: bool, keep: bool) -> int:
    from . import transcribe

    wav = session / "audio.wav"
    transcript_path = session / "transcript.txt"

    if not transcript_path.is_file():
        audio = recorder.compress(wav) if wav.suffix == ".wav" and wav.is_file() else wav
        if not audio.is_file():
            raise SystemExit(f"error: no audio at {audio}")
        text = transcribe.run(audio, vocab)
        transcript_path.write_text(text, encoding="utf-8")
        words = len(text.split())
        log(f"  transcript: {words} words -> {transcript_path}")
        if audio != wav:
            audio.unlink(missing_ok=True)
    else:
        text = transcript_path.read_text(encoding="utf-8")

    out = notes.generate(text, mode, vocab)

    suffix = {"excalidraw": "json", "png": "png"}.get(mode, "md")
    out_path = session / f"notes-{mode}.{suffix}"
    if isinstance(out, bytes):
        out_path.write_bytes(out)
        clipboard.copy_png(out)
    else:
        out_path.write_text(out, encoding="utf-8")
        clipboard.copy(out)
    _write_meta(session, mode=mode, vocab=vocab)
    _set_last(session)

    if not keep:
        wav.unlink(missing_ok=True)
        wav.with_suffix(".stats.json").unlink(missing_ok=True)

    target = {"excalidraw": "Excalidraw (paste on the canvas)",
              "png": "Notion / anywhere (it is an image)"}.get(mode, "Notion / Obsidian")
    log(f"\n  copied to clipboard — paste into {target}")
    log(f"  saved: {out_path}")

    detail = f"{len(text.split())} words in"
    notify.done(mode, detail)

    if show:
        print("\n" + "-" * 60)
        if isinstance(out, bytes):
            print(f"[PNG image, {len(out) / 1000:.0f} KB -> {out_path}]")
        else:
            print(out if mode != "excalidraw" else json.dumps(json.loads(out))[:400] + " ...")
        print("-" * 60)
    return 0


# --- commands -------------------------------------------------------------

def cmd_run(args) -> int:
    session = _new_session()
    wav = session / "audio.wav"
    device = args.device if args.device is not None else recorder.default_input()

    rec = recorder.Recorder(wav, device=device)
    thread = threading.Thread(target=rec.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    log(f"\n  ● listening  [{args.mode}]   press Enter to stop\n")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        log()
    rec.stop()
    thread.join(timeout=10)

    wav.with_suffix(".stats.json").write_text(
        json.dumps({"seconds": rec.seconds, "peak": rec.peak}), encoding="utf-8")

    log("  ■ stopped")
    _check_audio(wav, session)
    return _process(session, args.mode, args.vocab, args.show, args.keep)


def cmd_start(args) -> int:
    if config.CURRENT.is_file():
        state = json.loads(config.CURRENT.read_text())
        if _alive(state["pid"]):
            log(f"  already recording (pid {state['pid']}) — run `lecnote stop`")
            return 1
        config.CURRENT.unlink()

    session = _new_session()
    wav = session / "audio.wav"
    device = args.device if args.device is not None else recorder.default_input()

    logfile = (session / "recorder.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "lecnote.recproc", str(wav), str(device)],
        stdout=logfile, stderr=logfile,
        start_new_session=True,
        cwd=str(config.PROJECT_ROOT),
    )
    time.sleep(0.6)
    if proc.poll() is not None:
        print((session / "recorder.log").read_text(), file=sys.stderr)
        raise SystemExit("error: recorder failed to start (see log above)")

    config.CURRENT.write_text(json.dumps({
        "session": str(session), "pid": proc.pid, "mode": args.mode,
        "vocab": args.vocab, "started": time.time(),
    }), encoding="utf-8")
    _write_meta(session, mode=args.mode, vocab=args.vocab)

    log(f"  ● listening in background  [{args.mode}]   stop with: lecnote stop")
    return 0


def cmd_stop(args) -> int:
    if not config.CURRENT.is_file():
        raise SystemExit("error: nothing is recording.")
    state = json.loads(config.CURRENT.read_text())
    session = Path(state["session"])
    pid = state["pid"]

    if _alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            if not _alive(pid):
                break
            time.sleep(0.1)
    config.CURRENT.unlink(missing_ok=True)

    elapsed = time.time() - state.get("started", time.time())
    log(f"  ■ stopped after {elapsed:.0f}s")

    mode = args.mode_override or state.get("mode", DEFAULT_MODE)
    vocab = args.vocab or state.get("vocab", "")
    _check_audio(session / "audio.wav", session)
    return _process(session, mode, vocab, args.show, args.keep)


def cmd_toggle(args) -> int:
    """One command for both edges — bind it to a single hotkey."""
    recording = False
    if config.CURRENT.is_file():
        state = json.loads(config.CURRENT.read_text())
        recording = _alive(state["pid"])
    if recording:
        args.mode_override = getattr(args, "mode", None)
        return cmd_stop(args)
    return cmd_start(args)


def cmd_status(args) -> int:  # noqa: ARG001
    if config.CURRENT.is_file():
        state = json.loads(config.CURRENT.read_text())
        if _alive(state["pid"]):
            elapsed = time.time() - state.get("started", time.time())
            log(f"  ● recording  [{state['mode']}]  {elapsed:.0f}s  pid {state['pid']}")
            return 0
        log("  stale session file; clearing")
        config.CURRENT.unlink()
    session = _last_session()
    log("  idle" + (f"   last: {session}" if session else ""))
    return 0


def _all_sessions() -> list[Path]:
    """Newest first, only ones that actually have a transcript."""
    if not config.SESSIONS.is_dir():
        return []
    return sorted((d for d in config.SESSIONS.iterdir()
                   if d.is_dir() and (d / "transcript.txt").is_file()), reverse=True)


def _resolve_session(ref: str | None) -> Path:
    """Accept nothing (most recent), a 1-based index, or a name/prefix."""
    sessions = _all_sessions()
    if not sessions:
        raise SystemExit("error: no previous lecture to re-render.")
    if not ref:
        return sessions[0]
    if ref.isdigit():
        i = int(ref)
        if not 1 <= i <= len(sessions):
            raise SystemExit(f"error: no session {i} (there are {len(sessions)}). "
                             "Run `lecnote sessions`.")
        return sessions[i - 1]
    matches = [d for d in sessions if d.name.startswith(ref)]
    if not matches:
        raise SystemExit(f"error: no session matching '{ref}'. Run `lecnote sessions`.")
    return matches[0]


def cmd_sessions(args) -> int:  # noqa: ARG001
    """List captured lectures so `redo --session` has something to point at."""
    sessions = _all_sessions()
    if not sessions:
        log("  no lectures captured yet")
        return 0
    for i, d in enumerate(sessions, 1):
        meta = _read_meta(d)
        formats = sorted(f.suffix.lstrip(".") for f in d.glob("notes-*"))
        secs = meta.get("seconds")
        length = f"{secs / 60:.0f}m" if secs and secs >= 60 else (f"{secs:.0f}s" if secs else "—")
        snippet = " ".join((d / "transcript.txt").read_text(
            encoding="utf-8", errors="replace").split())[:60]
        log(f"  {i:>2}. {d.name}  {length:>4}  [{', '.join(formats) or 'no notes yet'}]"
            + (f"  {meta['vocab']}" if meta.get("vocab") else ""))
        log(f"      {snippet}...")
    log("\n  re-render any of them:  lecnote redo png --session 2")
    return 0


def cmd_redo(args) -> int:
    session = _resolve_session(args.session)
    meta = _read_meta(session)
    log(f"  re-rendering {session.name} as {args.mode}")
    return _process(session, args.mode, args.vocab or meta.get("vocab", ""), args.show, True)


def cmd_file(args) -> int:
    src = Path(args.path).expanduser()
    if not src.is_file():
        raise SystemExit(f"error: no such file: {src}")
    session = _new_session()
    dest = session / f"audio{src.suffix.lower()}"
    shutil.copy2(src, dest)
    _write_meta(session, source=str(src))

    from . import transcribe
    text = transcribe.run(dest, args.vocab)
    (session / "transcript.txt").write_text(text, encoding="utf-8")
    log(f"  transcript: {len(text.split())} words")
    return _process(session, args.mode, args.vocab, args.show, True)


def cmd_text(args) -> int:
    """Notes from an existing transcript file — no mic, no transcription cost."""
    src = Path(args.path).expanduser()
    if not src.is_file():
        raise SystemExit(f"error: no such file: {src}")
    session = _new_session()
    shutil.copy2(src, session / "transcript.txt")
    _write_meta(session, source=str(src))
    log(f"  transcript: {len(src.read_text(encoding='utf-8').split())} words from {src.name}")
    return _process(session, args.mode, args.vocab, args.show, True)


def cmd_transcript(args) -> int:
    session = _resolve_session(args.session)
    print((session / "transcript.txt").read_text(encoding="utf-8"))
    return 0


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def cmd_clean(args) -> int:
    """Delete old session folders. Keeps the newest few unless told otherwise."""
    sessions = sorted((d for d in config.SESSIONS.iterdir() if d.is_dir()), reverse=True)
    if not sessions:
        log("  no sessions to clean")
        return 0

    # Never touch a session that is still recording.
    active = None
    if config.CURRENT.is_file():
        state = json.loads(config.CURRENT.read_text())
        if _alive(state["pid"]):
            active = Path(state["session"])

    keep = 0 if args.all else args.keep
    doomed = sessions[keep:]
    if args.days:
        cutoff = time.time() - args.days * 86400
        doomed = [d for d in doomed if d.stat().st_mtime < cutoff]
    doomed = [d for d in doomed if d != active]

    if not doomed:
        log(f"  nothing to delete ({len(sessions)} sessions, keeping {min(keep, len(sessions))})")
        return 0

    total = sum(_dir_size(d) for d in doomed)
    log(f"  will delete {len(doomed)} session(s), freeing {total / 1e6:.1f} MB:")
    for d in doomed[:10]:
        log(f"    {d.name}  ({_dir_size(d) / 1e3:.0f} KB)")
    if len(doomed) > 10:
        log(f"    ... and {len(doomed) - 10} more")
    log(f"  keeping {len(sessions) - len(doomed)} session(s)"
        + (f", plus the active recording {active.name}" if active else ""))

    if not args.yes:
        try:
            if input("  delete these? [y/N] ").strip().lower() not in ("y", "yes"):
                log("  cancelled")
                return 1
        except (EOFError, KeyboardInterrupt):
            log("\n  cancelled")
            return 1

    for d in doomed:
        shutil.rmtree(d, ignore_errors=True)

    last = _last_session()
    if last is None and (config.HOME / "last.json").is_file():
        (config.HOME / "last.json").unlink()  # pointed at something just deleted
    log(f"  deleted {len(doomed)} session(s), freed {total / 1e6:.1f} MB")
    return 0


def cmd_devices(args) -> int:  # noqa: ARG001
    print(recorder.list_devices())
    print(f"\ndefault input: {recorder.default_input()}")
    return 0


def cmd_doctor(args) -> int:
    """Check keys, record a few seconds, and transcribe it back so you can see
    whether speech-to-text actually understood you — Hinglish included."""
    log("  checking keys...")
    for name in ("ANTHROPIC_API_KEY", "GROQ_API_KEY"):
        log(f"    {name}: {'set' if os.environ.get(name) else 'MISSING'}")

    device = args.device if args.device is not None else recorder.default_input()
    secs = args.seconds
    config.ensure_dirs()
    wav = config.HOME / "doctor.wav"

    rec = recorder.Recorder(wav, device=device)
    thread = threading.Thread(target=rec.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    log(f"\n  ● SPEAK NOW — recording {secs}s from device {device}")
    for left in range(secs, 0, -1):
        log(f"    {left}...")
        time.sleep(1)
    rec.stop()
    thread.join(timeout=5)
    log("  ■ stopped")

    log(f"\n    duration: {rec.seconds:.1f}s   peak level: {rec.peak:.4f}")
    if rec.peak < 0.001:
        log("\n  FAIL: pure silence. Grant microphone access:")
        log("    System Settings > Privacy & Security > Microphone > enable your terminal,")
        log("    then fully quit and reopen the terminal.")
        wav.unlink(missing_ok=True)
        return 1
    if rec.peak < 0.02:
        log("  WARN: very quiet. Move closer to the source or raise input volume.")
    else:
        log("  OK: microphone is working.")

    if args.no_stt:
        wav.unlink(missing_ok=True)
        return 0
    if not os.environ.get("GROQ_API_KEY"):
        log("\n  skipping the transcription check — GROQ_API_KEY is not set.")
        wav.unlink(missing_ok=True)
        return 0

    from . import transcribe
    log("\n  transcribing it back...")
    audio = recorder.compress(wav)
    try:
        heard = transcribe.run(audio, args.vocab)
    finally:
        wav.unlink(missing_ok=True)
        if audio != wav:
            audio.unlink(missing_ok=True)

    # log(), not print(), so this lands in order with the rest of the report
    log("\n  it heard:")
    log(f"    \"{heard.strip()}\"" if heard.strip() else "    (nothing)")
    if not heard.strip():
        log("\n  FAIL: audio recorded but nothing was transcribed. Speak louder or"
            " closer, and try `-s 8` for a longer sample.")
        return 1
    # Whisper's prompt parameter leaks into the output when the audio is unclear,
    # so a transcript that merely parrots the hint means it heard nothing useful.
    if args.vocab and heard.strip().lower().strip(".") in args.vocab.lower():
        log("\n  WARN: that is just the subject hint echoed back, which means the"
            " audio was too quiet to read.")
        log("  Speak louder or closer and run `lecnote doctor` again without -v.")
        return 1
    log("\n  OK: speech-to-text is working. Compare the line above with what you"
        " actually said —")
    log("  Hindi words should come back transliterated in Latin script.")
    return 0


# --- entry ----------------------------------------------------------------

def _mode_from_argv0() -> str | None:
    """`lecnote-notion` implies mode=notion. The launcher passes the name through."""
    name = os.environ.get("LECNOTE_INVOKED_AS") or Path(sys.argv[0]).name
    if "-" in name:
        candidate = name.rsplit("-", 1)[-1]
        if candidate in MODES:
            return candidate
    return None


def build_parser(default_mode: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lecnote",
        description="Record a lecture, get clean pastable notes on the clipboard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version",
                        version=f"lecnote {__version__}")

    def common(sub):
        sub.add_argument("-v", "--vocab", default="",
                         help="subject hint, e.g. 'subnetting, CIDR, IPv4' — improves both "
                              "transcription and note accuracy")
        sub.add_argument("-d", "--device", type=int, default=None,
                         help="input device index (see `lecnote devices`)")
        sub.add_argument("-p", "--show", action="store_true", help="also print notes to stdout")
        sub.add_argument("--keep", action="store_true", help="keep the audio file")
        return sub

    subs = parser.add_subparsers(dest="cmd")

    run = common(subs.add_parser("run", help="record now, Enter to stop (default)"))
    run.add_argument("mode", nargs="?", default=default_mode, choices=MODES)
    run.set_defaults(func=cmd_run)

    start = common(subs.add_parser("start", help="start recording in the background"))
    start.add_argument("mode", nargs="?", default=default_mode, choices=MODES)
    start.set_defaults(func=cmd_start)

    stop = common(subs.add_parser("stop", help="stop background recording and make notes"))
    stop.add_argument("mode_override", nargs="?", default=None, choices=MODES)
    stop.set_defaults(func=cmd_stop)

    redo = common(subs.add_parser("redo", help="re-render a captured lecture in another format"))
    redo.add_argument("mode", nargs="?", default=default_mode, choices=MODES)
    redo.add_argument("--session", default=None,
                      help="which lecture: a number from `lecnote sessions`, or its "
                           "name/prefix. Defaults to the most recent.")
    redo.set_defaults(func=cmd_redo)

    fil = common(subs.add_parser("file", help="process an existing audio file"))
    fil.add_argument("path")
    fil.add_argument("mode", nargs="?", default=default_mode, choices=MODES)
    fil.set_defaults(func=cmd_file)

    txt = common(subs.add_parser("text", help="make notes from an existing transcript file"))
    txt.add_argument("path")
    txt.add_argument("mode", nargs="?", default=default_mode, choices=MODES)
    txt.set_defaults(func=cmd_text)

    tog = common(subs.add_parser("toggle", help="start if idle, stop if recording"))
    tog.add_argument("mode", nargs="?", default=default_mode, choices=MODES)
    tog.set_defaults(func=cmd_toggle)

    clean = subs.add_parser("clean", help="delete old session folders")
    clean.add_argument("--keep", type=int, default=3,
                       help="how many recent sessions to keep (default 3)")
    clean.add_argument("--days", type=int, default=None,
                       help="only delete sessions older than this many days")
    clean.add_argument("--all", action="store_true", help="delete every session")
    clean.add_argument("-y", "--yes", action="store_true", help="skip the confirmation")
    clean.set_defaults(func=cmd_clean)

    subs.add_parser("sessions", help="list captured lectures").set_defaults(func=cmd_sessions)
    subs.add_parser("status", help="is anything recording?").set_defaults(func=cmd_status)
    tr = subs.add_parser("transcript", help="print a raw transcript")
    tr.add_argument("--session", default=None, help="which lecture (see `lecnote sessions`)")
    tr.set_defaults(func=cmd_transcript)
    subs.add_parser("devices", help="list audio input devices").set_defaults(func=cmd_devices)
    doc = subs.add_parser("doctor", help="check keys, mic, and transcription")
    doc.add_argument("-d", "--device", type=int, default=None)
    doc.add_argument("-s", "--seconds", type=int, default=6,
                     help="how long to record (default 6)")
    doc.add_argument("-v", "--vocab", default="",
                     help="subject hint, same as elsewhere")
    doc.add_argument("--no-stt", action="store_true",
                     help="only check the microphone, skip transcription")
    doc.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    config.load()
    config.ensure_dirs()
    argv = list(sys.argv[1:] if argv is None else argv)

    default_mode = _mode_from_argv0() or DEFAULT_MODE
    parser = build_parser(default_mode)

    # Bare `lecnote`, `lecnote notion`, or `lecnote -v x` means "record now".
    global_flags = {"-h", "--help", "--version"}
    if not argv or argv[0] in MODES or (argv[0].startswith("-") and argv[0] not in global_flags):
        argv = ["run"] + argv

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log("\n  cancelled")
        return 130
    except SystemExit as e:
        # A background run has no terminal to read; surface the reason.
        if isinstance(e.code, str) and args.cmd in ("run", "stop", "toggle", "file", "text", "redo"):
            notify.failed(e.code.replace("error: ", ""))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
