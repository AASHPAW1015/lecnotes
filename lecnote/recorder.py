"""Microphone capture to WAV, plus compression for upload.

WAV is written incrementally so a crash or a hard kill still leaves a playable
file. Compression to Ogg Vorbis happens once, after the recording stops.
"""

import queue
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from . import config


class Recorder:
    """Streams mic input into a WAV file until stopped."""

    def __init__(self, path: Path, device=None):
        self.path = Path(path)
        self.device = device
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
            channels=config.CHANNELS,
            device=self.device,
            dtype="float32",
            callback=self._callback,
            blocksize=1024,
        )
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
                f.write(block)
                self.frames += len(block)
                self.peak = max(self.peak, float(np.abs(block).max()))
            # Drain whatever the callback queued before the stop landed.
            while True:
                try:
                    block = self._q.get_nowait()
                except queue.Empty:
                    break
                f.write(block)
                self.frames += len(block)
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
        data, sr = sf.read(str(wav_path), dtype="float32")
        sf.write(str(ogg_path), data, sr, format="OGG", subtype="VORBIS")
    except Exception as e:  # noqa: BLE001 - fall back to raw WAV upload
        print(f"  note: compression unavailable ({e}); uploading WAV", file=sys.stderr)
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
    data, sr = sf.read(str(path), dtype="float32")

    out: list[Path] = []
    for i in range(parts):
        start = int(i * chunk_secs * sr)
        end = int(min((i + 1) * chunk_secs * sr, len(data)))
        if start >= end:
            continue
        chunk = path.with_name(f"{path.stem}.part{i:02d}{path.suffix}")
        if path.suffix == ".ogg":
            sf.write(str(chunk), data[start:end], sr, format="OGG", subtype="VORBIS")
        else:
            sf.write(str(chunk), data[start:end], sr, subtype="PCM_16")
        out.append(chunk)
    return out


def list_devices() -> str:
    return str(sd.query_devices())


def default_input() -> int | None:
    """sounddevice reports defaults as an (input, output) pair."""
    dev = sd.default.device
    try:
        return int(dev[0])
    except (TypeError, IndexError, ValueError):
        return dev if isinstance(dev, int) else None
