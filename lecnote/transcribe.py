"""Speech-to-text via Groq's hosted whisper-large-v3.

Chosen for Hinglish: whisper-large-v3 handles Hindi/English code-switching far
better than macOS dictation, and the hosted version needs no local compute.
Swappable — see BACKENDS at the bottom.
"""

import sys
from pathlib import Path

import httpx

from . import config, recorder

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class SttRejected(RuntimeError):
    """Provider refused the request for a reason the user can fix and retry.

    Raised from the per-chunk call, which only knows about a temporary chunk;
    run() catches it and names the real recording in the retry hint.
    """

MIME = {
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


def _groq_chunk(path: Path, prompt: str, language: str) -> str:
    key = config.groq_key()
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")

    with path.open("rb") as fh:
        files = {"file": (path.name, fh, mime)}
        data = {
            "model": config.STT_MODEL,
            "response_format": "text",
            "temperature": "0",
        }
        if language:
            data["language"] = language
        if prompt:
            # Whisper only reads the last ~224 tokens of the prompt.
            data["prompt"] = prompt[-800:]

        resp = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=300.0,
        )

    if resp.status_code in (401, 403):
        raise SttRejected("the Groq API key was rejected — most likely expired.\n"
                          "  Get a fresh one (free) at https://console.groq.com/keys and replace\n"
                          f"  GROQ_API_KEY in {config.HOME / '.env'} or the project .env")
    if resp.status_code == 429:
        raise SttRejected("Groq rate limit reached. Wait a minute before retrying")
    if resp.status_code != 200:
        raise SystemExit(f"error: Groq transcription failed ({resp.status_code})\n{resp.text[:500]}")
    return resp.text.strip()


def transcribe(audio: Path, vocab: str = "", language: str | None = None) -> str:
    """Transcribe an audio file, chunking it if it exceeds the upload cap.

    `vocab` seeds Whisper with domain terms (e.g. "subnet mask, CIDR, octet"),
    which measurably improves technical-term accuracy.
    """
    language = config.STT_LANG if language is None else language
    chunks = recorder.split(audio)

    if len(chunks) > 1:
        print(f"  audio is long; transcribing in {len(chunks)} chunks")

    out: list[str] = []
    carry = vocab
    for i, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            print(f"  chunk {i}/{len(chunks)}...")
        text = _groq_chunk(chunk, carry, language)
        out.append(text)
        # Carry the tail forward so the next chunk keeps context across the cut.
        carry = (vocab + "\n" + text)[-800:]
        if chunk != audio:
            chunk.unlink(missing_ok=True)

    return "\n".join(t for t in out if t).strip()


BACKENDS = {"groq": transcribe}


def run(audio: Path, vocab: str = "", backend: str = "groq") -> str:
    fn = BACKENDS.get(backend)
    if fn is None:
        raise SystemExit(f"error: unknown STT backend '{backend}' (have: {', '.join(BACKENDS)})")
    size_mb = audio.stat().st_size / 1e6
    print(f"  transcribing {audio.name} ({size_mb:.1f} MB) via {backend}/{config.STT_MODEL}...",
          file=sys.stderr)
    try:
        return fn(audio, vocab)
    except SttRejected as e:
        # The recording is already on disk, so this never costs a re-record.
        raise SystemExit(f"error: {e}.\n"
                         "  Nothing is lost — the audio is saved. Finish it with:\n"
                         f"    lecnote file {audio}") from None
