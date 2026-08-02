"""Configuration: API keys, model choices, paths."""

import os
from pathlib import Path

HOME = Path.home() / ".lecnote"
SESSIONS = HOME / "sessions"
CURRENT = HOME / "current.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1

# Whisper APIs cap uploads at 25MB; stay under it.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

# Models
NOTES_MODEL = os.environ.get("LECNOTE_MODEL", "claude-sonnet-5")

# How to reach Claude: "api" (prepaid API credits), "cli" (the `claude` command,
# billed to a Pro/Max subscription), or "auto" (API, falling back to CLI when the
# API credit balance is empty). A Pro subscription does not fund the API.
BACKEND = os.environ.get("LECNOTE_BACKEND", "auto")
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


def load() -> None:
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
        "Add it to .env in the project root, or export it in your shell.",
    )


def groq_key() -> str:
    return require(
        "GROQ_API_KEY",
        "Get a free key at https://console.groq.com/keys, then add GROQ_API_KEY to .env.\n"
        "  (Claude has no speech-to-text endpoint, so transcription needs a separate provider.)",
    )


def ensure_dirs() -> None:
    SESSIONS.mkdir(parents=True, exist_ok=True)
