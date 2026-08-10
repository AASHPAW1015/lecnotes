"""macOS clipboard write, text and images."""

import subprocess
import tempfile
from pathlib import Path


def copy(text: str) -> None:
    proc = subprocess.run(["pbcopy"], input=text.encode("utf-8"),
                          capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"error: pbcopy failed: {proc.stderr.decode(errors='replace')}")


def copy_files(paths) -> None:
    """Put several files on the pasteboard so one paste delivers them all.

    The image clipboard holds exactly one picture, which is no good for a
    lecture that yielded three flowcharts. File references can be a list, and
    apps that accept dropped files — Notion among them — take all of them from
    a single paste.
    """
    paths = [Path(p).resolve() for p in paths]
    items = ", ".join(f'POSIX file "{p}" as alias' for p in paths)
    script = f"tell application \"Finder\" to set the clipboard to {{{items}}}"
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit("error: could not copy the images to the clipboard: "
                         + proc.stderr.decode(errors="replace").strip())


def copy_png(data: bytes) -> None:
    """Put a real image on the pasteboard, so apps paste a picture not a filename.

    pbcopy only handles text; AppleScript can load PNG data as an image class,
    and macOS then offers it to apps as TIFF/JPEG/etc automatically.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        fh.write(data)
        tmp = Path(fh.name)
    try:
        script = (f'set the clipboard to (read (POSIX file "{tmp}") '
                  f'as \u00abclass PNGf\u00bb)')
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, check=False)
        if proc.returncode != 0:
            raise SystemExit("error: could not copy the image to the clipboard: "
                             + proc.stderr.decode(errors="replace").strip())
    finally:
        tmp.unlink(missing_ok=True)
