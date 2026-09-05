"""
Manual one-off: send a single wav to the Mac Studio.

The worker (worker.py) is what the batch pipeline uses. This file is
for poking the Studio by hand:

    python send_wav_file.py
    python send_wav_file.py /path/to/other.wav
"""

import sys
from pathlib import Path

from studio import transcribe_wav

DEFAULT = Path(__file__).resolve().parent / "test.wav"


if __name__ == "__main__":
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    print(transcribe_wav(wav))
