"""Detached recorder process, launched by `lecnote start`.

Records until it receives SIGTERM/SIGINT, then finalizes the WAV and exits.
Run as: python -m lecnote.recproc <wav_path> [device]
"""

import json
import signal
import sys
from pathlib import Path

from .recorder import Recorder


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m lecnote.recproc <wav_path> [device]", file=sys.stderr)
        return 2

    wav = Path(sys.argv[1])
    device = None
    if len(sys.argv) > 2 and sys.argv[2] not in ("", "None"):
        raw = sys.argv[2]
        device = int(raw) if raw.lstrip("-").isdigit() else raw

    rec = Recorder(wav, device=device)

    def handle(signum, frame):  # noqa: ARG001
        rec.stop()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    try:
        rec.run()
    finally:
        # Leave a breadcrumb so `stop` can report level/duration.
        wav.with_suffix(".stats.json").write_text(
            json.dumps({"seconds": rec.seconds, "peak": rec.peak}),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
