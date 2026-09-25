"""Record a single application's audio via a Core Audio process tap.

The capture itself is a small Swift helper (tap.swift): process taps are a
Core Audio API with no Python binding. It is compiled on first use and cached
in ~/.lecnote/bin, and rebuilt whenever the source is newer than the binary.

Unlike the BlackHole route this needs no virtual device and no change to the
system output: the app keeps playing to your earphones, other apps are left
out, and the volume keys keep working. It does need the app that launches
lecnote (iTerm, Raycast) to be allowed to record system audio.
"""

import json
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from . import config

SOURCE = Path(__file__).with_name("tap.swift")
PLIST = Path(__file__).with_name("tap-Info.plist")
BINARY = config.HOME / "bin" / "lecnote-tap"

PERMISSION_HELP = (
    "  macOS returns silence, not an error, until the app that started lecnote is\n"
    "  allowed to record system audio:\n"
    "    System Settings > Privacy & Security > Screen & System Audio Recording\n"
    "    > System Audio Recording Only > + > add your terminal and Raycast.")


def binary() -> Path:
    """Path to a current build of the helper, compiling it if needed."""
    if BINARY.is_file() and BINARY.stat().st_mtime >= SOURCE.stat().st_mtime:
        return BINARY
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise SystemExit(
            "error: per-app capture needs the Swift compiler, which is not installed.\n"
            "  Install the command line tools with:  xcode-select --install")
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    print("  building the app-audio helper (first run only)...", file=sys.stderr)
    # The Info.plist is linked into the binary: it carries the usage string
    # macOS shows when asking for system-audio permission.
    proc = subprocess.run(
        [swiftc, "-O", "-swift-version", "5", "-o", str(BINARY), str(SOURCE),
         "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT",
         "-Xlinker", "__info_plist", "-Xlinker", str(PLIST)],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit("error: could not build the app-audio helper:\n"
                         + proc.stderr.strip()[-1500:])
    return BINARY


def list_apps() -> str:
    proc = subprocess.run([str(binary()), "list"], capture_output=True, text=True, check=False)
    return (proc.stdout + proc.stderr).rstrip()


def record_argv(app: str, wav: Path) -> list[str]:
    return [str(binary()), "record", "--app", app, "--out", str(wav)]


class TapRecorder:
    """Same shape as recorder.Recorder: run() blocks until stop() is called."""

    def __init__(self, path: Path, app: str):
        self.path = Path(path)
        self.app = app
        self.argv = record_argv(app, self.path)  # build before the timer starts
        self._proc: subprocess.Popen | None = None
        self.seconds = 0.0
        self.peak = 0.0

    def run(self) -> Path:
        self._proc = subprocess.Popen(self.argv, stderr=subprocess.PIPE, text=True)
        for line in self._proc.stderr:  # "tapping 'firefox': 2 process(es)..."
            print("  " + line.rstrip(), file=sys.stderr)
        self._proc.wait()
        stats = self.path.with_suffix(".stats.json")
        if stats.is_file():
            data = json.loads(stats.read_text())
            self.seconds, self.peak = data["seconds"], data["peak"]
        return self.path

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
