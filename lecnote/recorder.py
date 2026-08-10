"""Microphone capture to WAV, plus compression for upload.

WAV is written incrementally so a crash or a hard kill still leaves a playable
file. Compression to Ogg Vorbis happens once, after the recording stops.
"""

import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from . import config

# Encode and split in blocks rather than one call. libsndfile's Vorbis encoder
# builds per-call scratch on the stack, so handing it a whole lecture at once
# (6M+ frames) overflows the stack and takes the process down with SIGSEGV —
# uncatchable, so the fallback below never got a chance to run. ~4s at 16 kHz.
BLOCK = 1 << 16


class Recorder:
    """Streams mic input into a WAV file until stopped."""

    def __init__(self, path: Path, device=None, channels: int | None = None):
        self.path = Path(path)
        self.device = device
        # Virtual devices like BlackHole are stereo, and asking a stereo device
        # for one channel fails outright on Core Audio. Open at whatever the
        # device offers and fold to mono on the way to disk, which is what
        # Whisper wants anyway.
        self.channels = channels or input_channels(device)
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self.peak = 0.0
        self.frames = 0

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"  audio warning: {status}", file=sys.stderr)
        self._q.put(indata.copy())

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> Path:
        """Blocks until stop() is called from another thread or a signal."""
        stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=self.channels,
            device=self.device,
            dtype="float32",
            callback=self._callback,
            blocksize=1024,
        )

        def write(block):
            if block.ndim > 1 and block.shape[1] > 1:
                block = block.mean(axis=1, keepdims=True)
            f.write(block)
            self.frames += len(block)
            self.peak = max(self.peak, float(np.abs(block).max()))

        with sf.SoundFile(
            self.path, mode="w",
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            subtype="PCM_16",
        ) as f, stream:
            while not self._stop.is_set():
                try:
                    block = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                write(block)
            # Drain whatever the callback queued before the stop landed.
            while True:
                try:
                    block = self._q.get_nowait()
                except queue.Empty:
                    break
                write(block)
        return self.path

    @property
    def seconds(self) -> float:
        return self.frames / config.SAMPLE_RATE


def duration(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / info.samplerate


def compress(wav_path: Path) -> Path:
    """Convert WAV to Ogg Vorbis so long lectures fit under the upload cap.

    Returns the original path if compression is unavailable or not a win.
    """
    ogg_path = wav_path.with_suffix(".ogg")
    try:
        with sf.SoundFile(str(wav_path)) as src:
            with sf.SoundFile(str(ogg_path), "w", samplerate=src.samplerate,
                              channels=src.channels, format="OGG",
                              subtype="VORBIS") as dst:
                for block in src.blocks(blocksize=BLOCK, dtype="float32"):
                    dst.write(block)
    except Exception as e:  # noqa: BLE001 - fall back to raw WAV upload
        print(f"  note: compression unavailable ({e}); uploading WAV", file=sys.stderr)
        ogg_path.unlink(missing_ok=True)
        return wav_path
    if ogg_path.stat().st_size >= wav_path.stat().st_size:
        ogg_path.unlink(missing_ok=True)
        return wav_path
    return ogg_path


def split(path: Path, max_bytes: int = config.MAX_UPLOAD_BYTES) -> list[Path]:
    """Split audio into chunks that each fit under max_bytes."""
    size = path.stat().st_size
    if size <= max_bytes:
        return [path]

    total = duration(path)
    parts = int(size // max_bytes) + 1
    chunk_secs = total / parts

    out: list[Path] = []
    with sf.SoundFile(str(path)) as src:
        sr = src.samplerate
        is_ogg = path.suffix == ".ogg"
        kwargs = ({"format": "OGG", "subtype": "VORBIS"} if is_ogg
                  else {"subtype": "PCM_16"})
        for i in range(parts):
            start = int(i * chunk_secs * sr)
            end = int(min((i + 1) * chunk_secs * sr, src.frames))
            if start >= end:
                continue
            chunk = path.with_name(f"{path.stem}.part{i:02d}{path.suffix}")
            src.seek(start)
            remaining = end - start
            with sf.SoundFile(str(chunk), "w", samplerate=sr,
                              channels=src.channels, **kwargs) as dst:
                while remaining > 0:
                    block = src.read(min(BLOCK, remaining), dtype="float32")
                    if not len(block):
                        break
                    dst.write(block)
                    remaining -= len(block)
            out.append(chunk)
    return out


def list_devices() -> str:
    return str(sd.query_devices())


def input_channels(device, cap: int = 2) -> int:
    """Channel count to open a device with, capped since we fold to mono anyway."""
    try:
        info = sd.query_devices(device if device is not None else sd.default.device[0])
        return max(1, min(int(info["max_input_channels"]), cap))
    except Exception:  # noqa: BLE001 - fall back to mono and let the stream complain
        return 1


def find_input(name_hint: str) -> int | None:
    """Index of the first input device whose name contains name_hint."""
    hint = name_hint.lower()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and hint in dev["name"].lower():
            return i
    return None


def loopback_device() -> int | None:
    """The virtual device carrying system audio, if one is installed."""
    for hint in config.LOOPBACK_HINTS:
        idx = find_input(hint)
        if idx is not None:
            return idx
    return None


# Output devices that exist to route audio rather than play it. Switching *to*
# one of these is how capture is enabled; switching away restores normal sound.
VIRTUAL_OUTPUT_HINTS = ("blackhole", "multi-output", "aggregate",
                        "soundflower", "loopback", "steam streaming")


def is_capture_output(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in VIRTUAL_OUTPUT_HINTS)


def _switch(*args: str) -> str:
    """Run SwitchAudioSource, which is how output is changed from a script."""
    exe = shutil.which("SwitchAudioSource")
    if not exe:
        raise SystemExit(
            "error: SwitchAudioSource is not installed, so the output cannot be\n"
            "  changed from the command line. Install it with:\n"
            "    brew install switchaudio-osx")
    proc = subprocess.run([exe, *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"error: SwitchAudioSource failed: "
                         f"{(proc.stderr or proc.stdout).strip()[:200]}")
    return proc.stdout.strip()


def current_output() -> str:
    return _switch("-c", "-t", "output")


def outputs() -> list[str]:
    return [ln.strip() for ln in _switch("-a", "-t", "output").splitlines() if ln.strip()]


def set_output(name: str) -> None:
    _switch("-s", name, "-t", "output")


def capture_output() -> str | None:
    """The output that feeds the loopback: a Multi-Output device, ideally."""
    names = outputs()
    for want in ("multi-output", "aggregate"):
        for n in names:
            if want in n.lower():
                return n
    # BlackHole alone works but is silent to the ears, so only as a last resort.
    return next((n for n in names if "blackhole" in n.lower()), None)


def speaker_output() -> str | None:
    """A real output — what to fall back to when capture is turned off."""
    return next((n for n in outputs() if not is_capture_output(n)), None)


def device_name(device) -> str:
    try:
        return str(sd.query_devices(device)["name"])
    except Exception:  # noqa: BLE001
        return str(device)


def default_output_name() -> str:
    """Name of the current system output, to check it routes into the loopback."""
    try:
        out = sd.default.device[1]
        return str(sd.query_devices(out)["name"])
    except Exception:  # noqa: BLE001
        return ""


def default_input() -> int | None:
    """sounddevice reports defaults as an (input, output) pair."""
    dev = sd.default.device
    try:
        return int(dev[0])
    except (TypeError, IndexError, ValueError):
        return dev if isinstance(dev, int) else None
