"""macOS clipboard write, text and images."""

import subprocess
import sys
import tempfile
from pathlib import Path


def copy(text: str) -> None:
    proc = subprocess.run(["pbcopy"], input=text.encode("utf-8"),
                          capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"error: pbcopy failed: {proc.stderr.decode(errors='replace')}")


def copy_files(paths) -> None:
    """Put several files on the pasteboard so one paste delivers them all.

    The image pasteboard holds exactly one picture, which is no good for a
    lecture that produced three flowcharts. Writing file URLs instead lets an
    app that accepts dropped files — Notion among them — take every one of them
    from a single paste.

    This needs the real pasteboard API. AppleScript can only put its own alias
    objects on the board, which Finder understands and nothing else does, so it
    is kept as a degraded fallback rather than the main path.
    """
    paths = [Path(p).resolve() for p in paths]
    try:
        from AppKit import NSURL, NSPasteboard
    except ImportError:
        _copy_files_applescript(paths)
        return

    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    if not board.writeObjects_([NSURL.fileURLWithPath_(str(p)) for p in paths]):
        raise SystemExit("error: the pasteboard refused the images.")


def _copy_files_applescript(paths) -> None:
    """Fallback for a machine without pyobjc. Pastes into Finder, little else."""
    items = ", ".join(f'POSIX file "{p}" as alias' for p in paths)
    proc = subprocess.run(
        ["osascript", "-e", f'tell application "Finder" to set the clipboard to {{{items}}}'],
        capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit("error: could not copy the images to the clipboard: "
                         + proc.stderr.decode(errors="replace").strip())
    print("  note: install pyobjc-framework-Cocoa for images that paste into Notion",
          file=sys.stderr)


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
