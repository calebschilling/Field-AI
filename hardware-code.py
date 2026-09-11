# this is temporary file for hardware code
# we will move this to esp32 code in the future, this is
# for prototyping purposes
from gpiozero import Button, LED
from signal import pause
import shutil
import subprocess
import threading
import time
import requests
from pathlib import Path
from datetime import datetime

# ---- Config ----
BACKEND_URL = "https://schilling-industries-linux.tail3eb284.ts.net"
FIELD_UPLOAD_KEY = ""  # same value as Field-AI FIELD_UPLOAD_KEY
RECORDINGS_DIR = Path.home() / "recordings"
SENT_DIR = RECORDINGS_DIR / "sent"
CHECK_INTERVAL = 15  # seconds between connectivity checks
# Tailscale from a Pi Zero can crawl (~30–50 KB/s). Size the read
# timeout from that floor so big backlog files can still finish.
MIN_UPLOAD_BPS = 30_000
# Anything above this gets downsampled before send (speech → Whisper).
SHRINK_ABOVE_BYTES = 8 * 1024 * 1024

RECORDINGS_DIR.mkdir(exist_ok=True)
SENT_DIR.mkdir(exist_ok=True)

button = Button(23, bounce_time=0.2)
led = LED(22)

recording_process = None
current_filename = None


# ---- Recording (button-driven, works fully offline) ----
def toggle_recording():
    global recording_process, current_filename

    if recording_process is None:
        current_filename = RECORDINGS_DIR / datetime.now().strftime("recording_%Y%m%d_%H%M%S.wav")
        print(f"Starting recording: {current_filename.name}")
        recording_process = subprocess.Popen([
            "arecord", "-D", "plughw:0,0",
            "-f", "S16_LE", "-r", "16000", "-c", "1",
            str(current_filename)
        ])
        led.on()
    else:
        print("Stopping recording")
        recording_process.terminate()
        recording_process.wait()
        recording_process = None
        led.off()
        print(f"Saved: {current_filename.name}")


button.when_pressed = toggle_recording


# ---- Background sync (network-driven, independent of button) ----
def backend_reachable() -> bool:
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def shrink_for_upload(path: Path) -> Path:
    """
    Old 48 kHz stereo clips are huge. Downsample to 16 kHz mono S16
    on the Pi before POST so Tailscale can finish. New recordings
    already match that format and skip this when small enough.
    """
    size = path.stat().st_size
    if size < SHRINK_ABOVE_BYTES:
        return path

    out = path.with_name(path.stem + ".upload.wav")
    if out.is_file() and out.stat().st_size > 0:
        print(f"Reusing shrink {out.name} ({out.stat().st_size / 1e6:.1f} MB)")
        return out

    print(f"Shrinking {path.name} ({size / 1e6:.1f} MB) → 16 kHz mono…")
    if _have("sox"):
        cmd = [
            "sox", str(path),
            "-r", "16000", "-c", "1", "-b", "16",
            str(out),
        ]
    elif _have("ffmpeg"):
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
            str(out),
        ]
    else:
        print("No sox/ffmpeg — uploading original (install sox on the Pi)")
        return path

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Shrink failed: {exc}")
        if out.is_file():
            out.unlink(missing_ok=True)
        return path

    print(f"Shrunk to {out.stat().st_size / 1e6:.1f} MB")
    return out


def upload_timeout(path: Path) -> tuple[float, float]:
    """Connect 10s; read long enough for worst-case Tailscale speed."""
    seconds = max(120, int(path.stat().st_size / MIN_UPLOAD_BPS) + 60)
    return (10, seconds)


def upload_file(path: Path) -> bool:
    payload = shrink_for_upload(path)
    timeout = upload_timeout(payload)
    print(
        f"POST {payload.name} ({payload.stat().st_size / 1e6:.1f} MB) "
        f"timeout={timeout[1]}s"
    )
    try:
        with payload.open("rb") as f:
            r = requests.post(
                f"{BACKEND_URL}/audio",
                files={"file": (path.name, f, "audio/wav")},
                headers={"X-Field-Key": FIELD_UPLOAD_KEY},
                timeout=timeout,
            )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Upload failed for {path.name}: {e}")
        return False
    finally:
        if payload != path and payload.is_file():
            # Keep .upload.wav on failure so the next try does not re-encode.
            # Deleted after a successful send in sync_loop.
            pass


def sync_loop():
    while True:
        if backend_reachable():
            pending = sorted(
                p for p in RECORDINGS_DIR.glob("*.wav")
                if not p.name.endswith(".upload.wav")
            )
            if pending:
                print(f"Backend online. {len(pending)} file(s) to send.")
            for path in pending:
                if path == current_filename and recording_process is not None:
                    continue
                print(f"Uploading {path.name}...")
                if upload_file(path):
                    upload_side = path.with_name(path.stem + ".upload.wav")
                    path.rename(SENT_DIR / path.name)
                    if upload_side.is_file():
                        upload_side.unlink(missing_ok=True)
                    print(f"Sent: {path.name}")
        time.sleep(CHECK_INTERVAL)


sync_thread = threading.Thread(target=sync_loop, daemon=True)
sync_thread.start()

print("Ready. Press button to start/stop recording. Syncing in background when online.")
pause()
