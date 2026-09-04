#!/usr/bin/env python3
"""Feeds a live "greeting" audio channel into the camera's RTSP stream.

camera_rtsp_server.py's ffmpeg pipeline reads FIFO_PATH as a third input
and mixes it with the live mic audio via amix, so a clip POSTed to /play
here gets heard by anyone watching the live stream, mixed in real time
with the room audio - not a local-only sound. Silence is written to the
FIFO the rest of the time so ffmpeg always has a continuous, valid source
to read even when nothing is playing.

recognize_rtsp.py (on the server) POSTs raw PCM here after a known/unknown
detection - see greet_stream.py there for the TTS generation side. PCM
must already match SAMPLE_RATE/CHANNELS/SAMPLE_WIDTH below (resampling
happens on the server side before sending).
"""
import os
import threading
import time

from flask import Flask, request

FIFO_PATH = "/tmp/greet_audio.pcm"
PORT = 5055

SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes (s16le)

CHUNK_FRAMES = 4410  # 0.1s per write chunk
CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * SAMPLE_WIDTH
SILENCE_CHUNK = b"\x00" * CHUNK_BYTES

app = Flask(__name__)

_lock = threading.Lock()
_pending_clip = None


CHUNK_SECONDS = CHUNK_FRAMES / SAMPLE_RATE


def _write_chunks_paced(fifo, data, next_write_at):
    """Write data in CHUNK_BYTES pieces, one per CHUNK_SECONDS of wall
    time - see _feeder_loop() for why this matters. Returns the updated
    next_write_at for the caller to keep pacing from.
    """
    for i in range(0, len(data), CHUNK_BYTES):
        now = time.monotonic()
        if next_write_at > now:
            time.sleep(next_write_at - now)

        fifo.write(data[i:i + CHUNK_BYTES])
        next_write_at += CHUNK_SECONDS

    return next_write_at


def _feeder_loop():
    """Keeps the FIFO fed - a queued clip if one's pending, else silence -
    paced to real wall-clock time.

    ffmpeg's raw-PCM demuxer (`-f s16le`, no `-re`) reads as fast as the
    pipe delivers data rather than at playback speed - only a genuinely
    live source like ALSA capture paces itself naturally. Writing
    silence as fast as the pipe accepts it let ffmpeg race far ahead
    into a large buffered backlog of old silence, so a newly-posted clip
    wouldn't reach the amix filter (and the live stream) for many
    seconds after it was queued here - confirmed via FFT analysis of a
    captured stream showing no trace of a posted test tone. Pacing
    writes to CHUNK_SECONDS of wall time each keeps this FIFO's rate
    matched to the mic's, so amix mixes them in sync instead of one
    racing ahead of the other.

    Reopens the FIFO whenever the reader (ffmpeg, in
    camera_rtsp_server.py) goes away and comes back, e.g. across that
    process's own restarts.
    """
    global _pending_clip

    while True:
        try:
            fifo = open(FIFO_PATH, "wb", buffering=0)
        except OSError as e:
            print(f"Waiting for FIFO reader: {e}", flush=True)
            time.sleep(2)
            continue

        print("Greeting audio feeder attached to FIFO", flush=True)

        next_write_at = time.monotonic()

        try:
            while True:
                with _lock:
                    clip = _pending_clip
                    _pending_clip = None

                if clip:
                    next_write_at = _write_chunks_paced(fifo, clip, next_write_at)
                else:
                    now = time.monotonic()
                    if next_write_at > now:
                        time.sleep(next_write_at - now)
                    fifo.write(SILENCE_CHUNK)
                    next_write_at += CHUNK_SECONDS

        except BrokenPipeError:
            print("FIFO reader gone, reattaching...", flush=True)
            fifo.close()
            continue


@app.route("/play", methods=["POST"])
def play():
    global _pending_clip

    audio = request.get_data()

    if not audio:
        return {"ok": False, "error": "empty body"}, 400

    with _lock:
        _pending_clip = audio

    return {"ok": True, "bytes": len(audio)}


@app.route("/health", methods=["GET"])
def health():
    return {"ok": True}


def main():
    if not os.path.exists(FIFO_PATH):
        os.mkfifo(FIFO_PATH)

    threading.Thread(target=_feeder_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
