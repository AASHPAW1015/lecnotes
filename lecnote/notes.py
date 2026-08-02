"""Transcript -> formatted notes, via Claude.

Sonnet is the default: this task needs reasoning (spot the teacher's mid-sentence
self-correction, drop the superseded value, reorder interleaved steps), not just
reformatting. Haiku tends to keep both the wrong and the right number, which
defeats the purpose. Override with LECNOTE_MODEL.

Two backends, because they bill from different pools:
  api  - api.anthropic.com, needs prepaid API credits
  cli  - the `claude` CLI in headless mode, runs on a Pro/Max subscription
A Pro subscription does not fund the API, so `auto` tries the API and falls back
to the CLI when the credit balance is empty.
"""

import os
import shutil
import subprocess
import sys
import tempfile

import anthropic

from . import config, excalidraw, prompts, render

MAX_TOKENS = 8000
CLI_TIMEOUT = 600

# Headless Claude Code would otherwise happily start reading the filesystem.
_NO_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep",
             "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit"]


class OutOfCredits(RuntimeError):
    pass


def generate(transcript: str, mode: str, vocab: str = "",
             backend: str | None = None) -> str | bytes:
    """Return clipboard-ready text for the given mode."""
    if not transcript.strip():
        raise SystemExit("error: transcript is empty — nothing was heard. Run `lecnote doctor`.")

    backend = backend or config.BACKEND
    system = prompts.system_prompt(mode, vocab)
    user = prompts.user_prompt(transcript)

    if backend == "cli":
        raw = _via_cli(system, user)
    elif backend == "api":
        config.anthropic_key()  # explicit backend: fail loudly on a missing key
        raw = _via_api(system, user)
    elif backend == "auto":
        try:
            raw = _via_api(system, user)
        except OutOfCredits as e:
            print(f"  API unavailable ({e}); using the claude CLI (subscription) instead",
                  file=sys.stderr)
            raw = _via_cli(system, user)
    else:
        raise SystemExit(f"error: unknown backend '{backend}' (use auto, api, or cli)")

    raw = raw.strip()
    if mode == "excalidraw":
        return excalidraw.to_clipboard_json(excalidraw.parse_spec(raw))
    if mode == "png":
        return render.render(excalidraw.parse_spec(raw))
    return _strip_fence(raw)


def _via_api(system: str, user: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise OutOfCredits("no ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key)
    print(f"  writing notes with {config.NOTES_MODEL} (API)...", file=sys.stderr)
    chunks: list[str] = []
    try:
        with client.messages.stream(
            model=config.NOTES_MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0.2,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                chunks.append(text)
    except anthropic.APIStatusError as e:
        if e.status_code == 400 and "credit balance" in str(getattr(e, "body", e)).lower():
            raise OutOfCredits("credit balance empty") from None
        raise SystemExit(_explain(e)) from None
    return "".join(chunks)


def _via_cli(system: str, user: str) -> str:
    """Headless `claude -p`. Bills against the Pro/Max subscription, not API credits."""
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit(
            "error: the `claude` CLI is not installed, and the API has no credits.\n"
            "  Install it (https://claude.com/claude-code) or add API credits at\n"
            "  https://console.anthropic.com/settings/billing")

    print(f"  writing notes with {config.NOTES_MODEL} (claude CLI)...", file=sys.stderr)
    cmd = [
        exe, "-p",
        "--model", config.NOTES_MODEL,
        "--system-prompt", system,
        "--output-format", "text",
        "--exclude-dynamic-system-prompt-sections",
        "--disallowed-tools", ",".join(_NO_TOOLS),
    ]
    # An ANTHROPIC_API_KEY in the environment takes precedence over the claude.ai
    # login, which is exactly backwards here — the whole point of this backend is
    # to use the subscription. Drop it for the child only.
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}

    # Run somewhere empty so no CLAUDE.md or repo context leaks into the notes.
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                              cwd=cwd, env=env, timeout=CLI_TIMEOUT, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"error: claude CLI failed ({proc.returncode})\n{proc.stderr[:500]}")
    if not proc.stdout.strip():
        raise SystemExit("error: claude CLI returned nothing.")
    return proc.stdout


def _explain(e: anthropic.APIStatusError) -> str:
    """Turn an API error into one actionable line. The transcript is already saved."""
    msg = getattr(getattr(e, "body", None), "get", lambda *_: None)("error") or {}
    detail = msg.get("message") if isinstance(msg, dict) else str(e)

    if e.status_code == 401:
        return ("error: ANTHROPIC_API_KEY was rejected.\n"
                "  Check the key in .env at https://console.anthropic.com/settings/keys")
    if e.status_code == 404 and "model" in str(detail).lower():
        return (f"error: model '{config.NOTES_MODEL}' is not available to this account.\n"
                "  Set LECNOTE_MODEL in .env to a model you have access to.")
    if e.status_code == 429:
        return "error: rate limited by the Anthropic API. Wait a moment, then `lecnote redo`."
    return f"error: Anthropic API returned {e.status_code}: {detail}"


def _strip_fence(text: str) -> str:
    """Drop a wrapping ```markdown fence if the model added one."""
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text
