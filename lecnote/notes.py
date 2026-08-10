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


class ApiUnavailable(RuntimeError):
    """The API cannot serve this request, but another backend might.

    Anything raised as this is a reason to try the CLI rather than to give up:
    no key, a rejected key, an exhausted balance. Errors that a different
    backend would not fix (a bad model name, a malformed request) are not.
    """


class OutOfCredits(ApiUnavailable):
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
        try:
            raw = _via_api(system, user)
        except ApiUnavailable as e:
            raise SystemExit(
                f"error: {e}.\n"
                "  Check the key at https://console.anthropic.com/settings/keys,\n"
                "  or set LECNOTE_BACKEND=cli to bill a subscription instead.") from None
    elif backend == "auto":
        try:
            raw = _via_api(system, user)
        except ApiUnavailable as e:
            print(f"  API unavailable ({e}); using the {config.NOTES_CLI} CLI "
                  "(subscription) instead", file=sys.stderr)
            raw = _via_cli(system, user)
    else:
        raise SystemExit(f"error: unknown backend '{backend}' (use auto, api, or cli)")

    raw = raw.strip()
    if mode == "excalidraw":
        # Every procedure in one scene, so a single paste drops them all on the
        # canvas side by side.
        return excalidraw.to_clipboard_json(excalidraw.parse_specs(raw))
    if mode == "png":
        # One image per procedure; the caller writes and copies them together.
        return [render.render(s) for s in excalidraw.parse_specs(raw)]
    return _strip_fence(raw)


def _via_api(system: str, user: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ApiUnavailable("no ANTHROPIC_API_KEY")
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
        # A revoked, rotated or mistyped key is as recoverable as an empty
        # balance — the subscription CLI can still do the work.
        if e.status_code in (401, 403):
            raise ApiUnavailable("ANTHROPIC_API_KEY rejected") from None
        raise SystemExit(_explain(e)) from None
    return "".join(chunks)


def _claude_argv(exe: str, model: str, system: str) -> list[str]:
    return [
        exe, "-p",
        "--model", model,
        "--system-prompt", system,
        "--output-format", "text",
        "--exclude-dynamic-system-prompt-sections",
        "--disallowed-tools", ",".join(_NO_TOOLS),
    ]


def _codex_argv(exe: str, model: str, _system: str) -> list[str]:
    # No dedicated system-prompt flag, so the system text is folded into stdin
    # by _via_cli. `--skip-git-repo-check` matters because we run in a temp dir.
    return [exe, "exec", "--model", model, "--skip-git-repo-check", "-"]


def _gemini_argv(exe: str, model: str, _system: str) -> list[str]:
    return [exe, "--model", model]


# Any CLI that can be driven non-interactively works here. `folds_system` says the
# CLI has no system-prompt flag, so the system text is prepended to stdin instead.
# `drops` names env vars that would make the CLI bill an API key rather than the
# subscription this backend exists to use.
CLI_BACKENDS = {
    "claude": {
        "argv": _claude_argv, "model": "claude-sonnet-5", "folds_system": False,
        "drops": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        "install": "https://claude.com/claude-code",
    },
    "codex": {
        "argv": _codex_argv, "model": "gpt-5.1-codex", "folds_system": True,
        "drops": ("OPENAI_API_KEY",),
        "install": "npm i -g @openai/codex, then `codex login` with your ChatGPT plan",
    },
    "gemini": {
        "argv": _gemini_argv, "model": "gemini-2.5-pro", "folds_system": True,
        "drops": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "install": "npm i -g @google/gemini-cli, then `gemini` once to sign in",
    },
}


def _via_cli(system: str, user: str) -> str:
    """Drive a vendor's coding CLI in headless mode.

    These bill against a chat subscription (Claude Pro/Max, ChatGPT Plus/Pro,
    Google AI Pro) rather than prepaid API credits, so they are the cheap path
    for anyone who already pays for one.
    """
    name = config.NOTES_CLI
    spec = CLI_BACKENDS.get(name)
    if spec is None:
        raise SystemExit(f"error: unknown LECNOTE_CLI '{name}' "
                         f"(have: {', '.join(CLI_BACKENDS)})")

    exe = shutil.which(name)
    if not exe:
        raise SystemExit(
            f"error: the `{name}` CLI is not installed, and the API has no credits.\n"
            f"  Install it: {spec['install']}\n"
            f"  Or pick another with LECNOTE_CLI ({', '.join(CLI_BACKENDS)}),\n"
            "  or add API credits at https://console.anthropic.com/settings/billing")

    model = config.MODEL_OVERRIDE or spec["model"]
    print(f"  writing notes with {model} ({name} CLI)...", file=sys.stderr)

    stdin = f"{system}\n\n---\n\n{user}" if spec["folds_system"] else user
    cmd = spec["argv"](exe, model, system)

    # An API key in the environment takes precedence over the browser login,
    # which is exactly backwards here. Drop it for the child only.
    env = {k: v for k, v in os.environ.items() if k not in spec["drops"]}

    # Run somewhere empty so no CLAUDE.md, AGENTS.md or repo context leaks in.
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                              cwd=cwd, env=env, timeout=CLI_TIMEOUT, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout)[:500]
        hint = ""
        if "login" in detail.lower() or "not logged in" in detail.lower():
            hint = f"\n  Run `{name}` once in a terminal and sign in, then retry."
        raise SystemExit(f"error: {name} CLI failed ({proc.returncode})\n{detail}{hint}")
    if not proc.stdout.strip():
        raise SystemExit(f"error: {name} CLI returned nothing.")
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
