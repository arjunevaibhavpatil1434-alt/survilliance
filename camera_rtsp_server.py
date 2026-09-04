#!/usr/bin/env python3
"""Publishes the CSI camera + USB mic to the server's mediamtx over RTSP.

Full flow: OV5647 -> libcamera (rpicam-vid, raw YUV420) -> ffmpeg (libx264
video + AAC audio from the USB mic via ALSA) -> RTSP -> mediamtx on the
server. This board is input-only: mediamtx, recording, and the
face-recognition pipeline all live on the server; see
config.yaml/recognize_rtsp.py there, whose mediamtx.yml has cam02
configured as `source: publisher`.

rpicam-vid's own H.264 codec path uses the same bcm2835-codec hardware
encoder that fails at the firmware level on this image (see git history
of this file for the MJPEG-only workaround that shipped before this), and
that encoder isn't even registered in v4l2-ctl's device list here. So this
captures raw YUV420 from rpicam-vid instead and encodes H.264 in software
via ffmpeg's libx264 (confirmed available in this image's ffmpeg build,
unlike gstreamer's x264enc) - the board's quad Cortex-A72 keeps up with
1280x720@15fps in the veryfast/zerolatency preset with room to spare, now
that recognition/dashboard no longer run here too.

A third audio input (GREET_FIFO) is mixed into the mic via amix - see
greet_audio_feeder.py, which keeps that FIFO fed with silence except when
the server POSTs it a "Hello, <name>"/"No match" clip after a detection,
so live stream viewers hear it mixed with the room's own audio in real
time, not just something played locally at the camera.
"""
import os
import shlex
import signal
import subprocess
import sys
import time

SERVER_HOST = "192.168.88.249"
SERVER_PORT = "8554"
SERVER_PATH = "/cam02"

WIDTH = 1280
HEIGHT = 720
FRAMERATE = 15

# USB mic - see `arecord -l` (Plantronics Blackwire 3220, card 2 on this
# board; re-check with `arecord -l` if the mic is ever swapped).
ALSA_DEVICE = "plughw:2,0"

# Must match greet_audio_feeder.py's FIFO_PATH/SAMPLE_RATE/CHANNELS.
GREET_FIFO = "/tmp/greet_audio.pcm"
GREET_SAMPLE_RATE = 44100

VIDEO_BITRATE = "1500k"
AUDIO_BITRATE = "128k"

RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60

RPICAM_CMD = (
    f"rpicam-vid -t 0 --width {WIDTH} --height {HEIGHT} "
    f"--framerate {FRAMERATE} --codec yuv420 --nopreview -o -"
)

FFMPEG_CMD = (
    f"ffmpeg -hide_banner -loglevel warning "
    f"-thread_queue_size 1024 -f rawvideo -pix_fmt yuv420p -s:v {WIDTH}x{HEIGHT} -r {FRAMERATE} -i - "
    f"-thread_queue_size 1024 -f alsa -ac 1 -ar 44100 -i {ALSA_DEVICE} "
    f"-thread_queue_size 1024 -f s16le -ar {GREET_SAMPLE_RATE} -ac 1 -i {GREET_FIFO} "
    f'-filter_complex "[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=0[aout]" '
    f'-map 0:v -map "[aout]" '
    f"-c:v libx264 -preset veryfast -tune zerolatency -b:v {VIDEO_BITRATE} -g {FRAMERATE} "
    f"-c:a aac -b:a {AUDIO_BITRATE} "
    f"-f rtsp -rtsp_transport tcp rtsp://{SERVER_HOST}:{SERVER_PORT}{SERVER_PATH}"
)


# init.d's stop/restart sends SIGTERM only to this process, and Python's
# default SIGTERM handling kills it immediately without running any
# cleanup - so without an explicit handler, rpicam-vid/ffmpeg are orphaned
# still holding the camera and the USB mic open, and the next start's
# children fail to open either device. Track the live children here so a
# handler can terminate them before this process exits.
_active_procs = []


def _shutdown(signum, _frame):
    for proc in _active_procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in _active_procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


def run_once():
    """Run rpicam-vid piped into ffmpeg until either side exits.

    Returns when the pipeline stops, so the caller can restart it - the
    server (and the network between here and it) can go away independently
    of this process (reboot, network hiccup, etc), and the USB mic or
    camera can also transiently fail to open.
    """

    # greet_audio_feeder.py also creates this if missing - whichever of
    # the two processes starts first wins, it's the same path either way.
    if not os.path.exists(GREET_FIFO):
        os.mkfifo(GREET_FIFO)

    rpicam = subprocess.Popen(
        shlex.split(RPICAM_CMD),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    ffmpeg = subprocess.Popen(
        shlex.split(FFMPEG_CMD),
        stdin=rpicam.stdout,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    _active_procs[:] = [rpicam, ffmpeg]

    # Let ffmpeg hold the only reference to rpicam's read end, so rpicam
    # gets SIGPIPE and exits promptly once ffmpeg does.
    rpicam.stdout.close()

    print(f"Publishing to rtsp://{SERVER_HOST}:{SERVER_PORT}{SERVER_PATH}", flush=True)

    ffmpeg_rc = ffmpeg.wait()
    rpicam.terminate()
    rpicam.wait()

    _active_procs.clear()

    return ffmpeg_rc == 0


def main():
    delay = RECONNECT_DELAY

    while True:
        ok = run_once()

        if ok:
            delay = RECONNECT_DELAY
        else:
            print(f"Pipeline exited with an error, retrying in {delay}s...", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY)


if __name__ == "__main__":
    main()
