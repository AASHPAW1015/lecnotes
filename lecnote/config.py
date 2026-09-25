"""Configuration: API keys, model choices, paths."""

import os
from pathlib import Path

HOME = Path.home() / ".lecnote"
SESSIONS = HOME / "sessions"
CURRENT = HOME / "current.json"
# One file per process turning audio into notes, so `status` can say what is
# still in flight after the recording itself has stopped.
PROCESSING = HOME / "processing"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1  # what we write to disk; inputs are folded down to mono

# macOS hands no app the system output mix, so capturing what the speakers play
# needs a virtual device that the audio is routed into first. Names to look for,
# most common first. Override with LECNOTE_SYSTEM_DEVICE for a different one.
LOOPBACK_HINTS = [h for h in [os.environ.get("LECNOTE_SYSTEM_DEVICE", "")] if h] or [
    "BlackHole", "Loopback Audio", "Soundflower", "Aggregate",
]

# Whisper APIs cap uploads at 25MB; stay under it.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

# Models. Blank override means "use whatever the chosen CLI defaults to", since a
# Claude model name is meaningless to the codex or gemini CLI.
MODEL_OVERRIDE = os.environ.get("LECNOTE_MODEL", "")
NOTES_MODEL = MODEL_OVERRIDE or "claude-sonnet-5"

# How to reach a model: "api" (prepaid Anthropic API credits), "cli" (a vendor's
# coding CLI, billed to a chat subscription), or "auto" (API, falling back to the
# CLI when the API credit balance is empty). A Pro subscription does not fund the API.
BACKEND = os.environ.get("LECNOTE_BACKEND", "auto")

# Which CLI the "cli" backend drives: claude, codex or gemini. See notes.CLI_BACKENDS.
NOTES_CLI = os.environ.get("LECNOTE_CLI", "claude")
STT_MODEL = os.environ.get("LECNOTE_STT_MODEL", "whisper-large-v3")

# Hinglish: "en" makes Whisper transliterate Hindi into Latin script instead of
# emitting Devanagari, which keeps the transcript readable and keeps technical
# terms in English. Override with LECNOTE_STT_LANG=hi to compare.
STT_LANG = os.environ.get("LECNOTE_STT_LANG", "en")


def _load_env_file(path: Path) -> None:
    """Minimal .env loader. Existing env vars always win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def _harden_env() -> None:
    """Repair the environment when launched by Raycast, Finder, launchd or cron.

    Those start us with a minimal environment rather than a login shell: PATH has
    no Homebrew (so the notes CLI looks uninstalled) and USER/SHELL may be unset
    (so that CLI cannot find its login and reports "Not logged in"). bin/lecnote
    does this too, but pip-installed entry points do not go through it.
    """
    extra = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin")]
    path = os.environ.get("PATH", "")
    missing = [p for p in extra if p not in path.split(":")]
    if missing:  # append, so a caller's own PATH still wins
        os.environ["PATH"] = ":".join(filter(None, [path, *missing]))
    if not os.environ.get("USER"):
        try:
            os.environ["USER"] = os.getlogin()
        except OSError:
            import pwd
            os.environ["USER"] = pwd.getpwuid(os.getuid()).pw_name
    os.environ.setdefault("SHELL", "/bin/zsh")


def load() -> None:
    _harden_env()
    _load_env_file(PROJECT_ROOT / ".env")
    _load_env_file(HOME / ".env")


def require(name: str, hint: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"error: {name} not set.\n  {hint}")
    return val


def anthropic_key() -> str:
    return require(
        "ANTHROPIC_API_KEY",
        f"Add it to {HOME / '.env'} (or .env in the project root), or export it.\n"
        "  No API credits? Set LECNOTE_BACKEND=cli to bill a chat subscription instead.",
    )


def groq_key() -> str:
    return require(
        "GROQ_API_KEY",
        "Get a free key at https://console.groq.com/keys, then add it to\n"
        f"  {HOME / '.env'} as GROQ_API_KEY=...\n"
        "  Transcription always needs this: no chat subscription covers speech-to-text.",
    )


def ensure_dirs() -> None:
    SESSIONS.mkdir(parents=True, exist_ok=True)
