"""Watches for the RTSP stream actually stalling, not just a process dying.

recognize_rtsp.py and camera_rtsp_server.py already retry-with-backoff on
their own read/publish failures, so most transient blips (a network hiccup,
a brief camera hang) self-heal with nobody needing to know. This exists for
the case that self-healing doesn't cover: a sustained outage where nobody
would otherwise notice, because nothing here pages anyone just for a
process staying "active" while producing no actual frames.

Run periodically (see stream-watchdog.timer, every 3 minutes). Each run is
one check: try to read a frame from mediamtx within a short timeout. State
(consecutive failure count) persists in STATE_FILE between runs, since each
invocation is a fresh process. On the Nth consecutive failure, restart the
RPi's camera-rtsp service (the most likely actual point of failure - see
README.md "What runs where") and send a Telegram alert either way, so a
human knows even if the remote restart itself couldn't be attempted. Sends
one more Telegram message on recovery, so an alert isn't the last anyone
hears about it.
"""
import json
import os
import subprocess
import sys
import time

import cv2

from config_loader import RTSP_URL, LOGS_DIR
from notify import send_message

STATE_FILE = os.path.join(LOGS_DIR, "watchdog_state.json")

READ_TIMEOUT_SECONDS = 10
FAILURES_BEFORE_ACTION = 3  # ~9 minutes of sustained outage at a 3-minute timer

RPI_HOST = "192.168.88.157"


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"consecutive_failures": 0, "alerted": False}


def _save_state(state):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def stream_is_flowing():
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            return False
        ret, _ = cap.read()
        return ret
    finally:
        cap.release()


def restart_rpi_camera_service():
    """Best-effort remote restart - failures here are logged, not raised,
    since the Telegram alert below fires either way and a human can
    intervene manually if the RPi's unreachable outright (e.g. actual
    power/network loss, which no restart command could fix anyway)."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", f"root@{RPI_HOST}",
             "/etc/init.d/camera-rtsp restart"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            return True, (result.stdout or "").strip()
        return False, (result.stdout + result.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)


def main():
    state = _load_state()

    if stream_is_flowing():
        if state["consecutive_failures"] >= FAILURES_BEFORE_ACTION and state["alerted"]:
            send_message(
                f"✅ Camera stream recovered after {state['consecutive_failures']} "
                f"consecutive failed checks."
            )
        state["consecutive_failures"] = 0
        state["alerted"] = False
        _save_state(state)
        print("stream OK", flush=True)
        return

    state["consecutive_failures"] += 1
    print(f"stream check failed ({state['consecutive_failures']} consecutive)", flush=True)

    if state["consecutive_failures"] >= FAILURES_BEFORE_ACTION and not state["alerted"]:
        restarted, detail = restart_rpi_camera_service()
        outcome = "restarted camera-rtsp on the RPi" if restarted else f"restart attempt failed: {detail}"

        send_message(
            f"⚠️ Camera stream has been down for "
            f"{state['consecutive_failures']} consecutive checks (~{state['consecutive_failures'] * 3} min). "
            f"{outcome}"
        )

        state["alerted"] = True

    _save_state(state)


if __name__ == "__main__":
    main()
