"""Voice greetings mixed live into the RTSP stream's own audio.

recognize_rtsp.py calls greet_known(name)/greet_unknown() after a
detection. Each generates "Hello, <name>"/"No match" with espeak, converts
it to raw PCM matching greet_audio_feeder.py's expected format, and POSTs
it to that service on the RPi, which mixes it into the live mic audio via
ffmpeg's amix (see camera_rtsp_server.py) - so anyone watching the live
stream hears it, not just something played locally at the camera.

Runs off the caller's thread (see notify.py for the same reasoning): the
RPi round-trip and espeak's own synth time shouldn't stall detection of
the next frame.
"""
import os
import subprocess
import tempfile
import threading
from datetime import datetime

import requests

from config_loader import LOGS_DIR

RPI_HOST = "192.168.88.157"
FEEDER_PORT = 5055
FEEDER_URL = f"http://{RPI_HOST}:{FEEDER_PORT}/play"

# Must match greet_audio_feeder.py's SAMPLE_RATE/CHANNELS/SAMPLE_WIDTH.
SAMPLE_RATE = 44100
CHANNELS = 1

LOG_FILE = os.path.join(LOGS_DIR, "events.log")


def _log_error(context, detail):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] GREETING ERROR ({context}): {detail}\n"

    print(line.strip())

    with open(LOG_FILE, "a") as f:
        f.write(line)


def _synthesize_pcm(text):
    """espeak's own WAV output is 22050Hz - resample to the feeder's
    44100Hz mono s16le via ffmpeg so it doesn't need per-request format
    detection on the RPi side.
    """

    with tempfile.NamedTemporaryFile(suffix=".wav") as wav_file:

        subprocess.run(
            ["espeak", "-w", wav_file.name, text],
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", wav_file.name,
                "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
                "-f", "s16le", "-",
            ],
            check=True,
            capture_output=True,
        )

    return result.stdout


def _play(text):
    try:
        pcm = _synthesize_pcm(text)
    except (subprocess.CalledProcessError, OSError) as e:
        _log_error("synthesize", f"{text!r}: {e}")
        return

    try:
        response = requests.post(FEEDER_URL, data=pcm, timeout=5)
        if not response.ok:
            _log_error("post", f"{text!r}: HTTP {response.status_code}")
    except requests.RequestException as e:
        _log_error("post", f"{text!r}: {e}")


def greet_known(name):
    threading.Thread(target=_play, args=(f"Hello, {name}",), daemon=True).start()


def greet_unknown():
    threading.Thread(target=_play, args=("No match",), daemon=True).start()
