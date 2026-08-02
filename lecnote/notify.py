"""macOS notifications, so a background run can tell you it finished.

Uses osascript, which is built in. Silently does nothing if notifications are
disabled or unavailable — a failed notification must never fail the run.
"""

import os
import subprocess


def _enabled() -> bool:
    return os.environ.get("LECNOTE_NOTIFY", "1") not in ("0", "false", "no")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send(title: str, message: str, sound: str | None = "Glass") -> None:
    if not _enabled():
        return
    script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    if sound:
        script += f' sound name "{_escape(sound)}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True,
                       timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def done(mode: str, detail: str = "") -> None:
    target = {"notion": "Notion", "obsidian": "Obsidian",
              "excalidraw": "Excalidraw"}.get(mode, mode)
    send("Notes ready", f"Copied — paste into {target}. {detail}".strip())


def failed(reason: str) -> None:
    send("lecnote failed", reason.splitlines()[0][:150], sound="Basso")
