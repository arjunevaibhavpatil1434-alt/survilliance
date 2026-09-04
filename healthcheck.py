"""End-to-end health check for the surveillance pipeline.

Verifies, in order: config/env load correctly, required Python packages are
importable, the known-faces directory has usable data, the sqlite schema is
present, the camera-rtsp/recognize/dashboard sysvinit services are active, the
RTSP stream is actually readable, the dashboard HTTP API responds, and (if
configured) the Telegram bot token is valid. Exits non-zero on the first
hard failure so `make verify` fails loudly instead of silently.
"""

import importlib
import os
import shutil
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK = "\033[32mOK\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

failures = []


def check(label, fn):
    try:
        detail = fn()
        print(f"[{OK}] {label}" + (f" - {detail}" if detail else ""))
        return True
    except Exception as e:
        print(f"[{FAIL}] {label} - {e}")
        failures.append(label)
        return False


def warn(label, fn):
    try:
        detail = fn()
        print(f"[{OK}] {label}" + (f" - {detail}" if detail else ""))
    except Exception as e:
        print(f"[{WARN}] {label} - {e}")


def check_config():
    import config_loader as c
    assert c.CAMERA_SOURCE_IP, "camera.source_ip missing from config.yaml"
    return f"RTSP target {c.RTSP_URL}"


def check_imports():
    for mod in ["cv2", "face_recognition", "flask", "yaml", "dotenv", "requests", "numpy"]:
        importlib.import_module(mod)
    return "cv2, face_recognition, flask, yaml, dotenv, requests, numpy"


def check_known_faces():
    import config_loader as c
    if not os.path.isdir(c.KNOWN_FACES_DIR):
        raise RuntimeError(f"{c.KNOWN_FACES_DIR} does not exist")
    people = [
        d for d in os.listdir(c.KNOWN_FACES_DIR)
        if os.path.isdir(os.path.join(c.KNOWN_FACES_DIR, d))
        and os.listdir(os.path.join(c.KNOWN_FACES_DIR, d))
    ]
    if not people:
        raise RuntimeError("no person subdirectories with images found")
    return f"{len(people)} known person(s): {', '.join(sorted(people))}"


def check_db():
    import config_loader as c
    if not os.path.exists(c.DB_FILE):
        raise RuntimeError(f"{c.DB_FILE} does not exist")
    conn = sqlite3.connect(c.DB_FILE)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for required in ("events", "attendance"):
        if required not in tables:
            raise RuntimeError(f"missing table '{required}'")
    return f"tables present: {sorted(tables)}"


def _initd_active(service):
    """This board runs sysvinit, not systemd - check via the service's own
    init script (LSB 'status' action) rather than systemctl."""
    result = subprocess.run(
        [f"/etc/init.d/{service}", "status"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout + result.stderr).strip() or "not running")
    return (result.stdout or "running").strip()


def check_camera_rtsp_service():
    return _initd_active("camera-rtsp")


def check_recognize_service():
    return _initd_active("sur-recognize")


def check_dashboard_service():
    return _initd_active("sur-dashboard")


def check_rtsp_stream():
    import cv2
    import config_loader as c
    cap = cv2.VideoCapture(c.RTSP_URL, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"could not open {c.RTSP_URL}")
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("opened stream but failed to read a frame")
        return f"frame shape {frame.shape}"
    finally:
        cap.release()


def check_dashboard_http():
    import urllib.error
    import urllib.request
    import base64
    import config_loader as c
    host = "127.0.0.1" if c.DASHBOARD_HOST == "0.0.0.0" else c.DASHBOARD_HOST
    url = f"http://{host}:{c.DASHBOARD_PORT}/"

    try:
        urllib.request.urlopen(url, timeout=5)
        raise RuntimeError("dashboard served a request with no credentials (auth not enforced)")
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise RuntimeError(f"expected 401 without credentials, got HTTP {e.code}")

    if not c.DASHBOARD_USERNAME or not c.DASHBOARD_PASSWORD:
        raise RuntimeError("DASHBOARD_USERNAME/PASSWORD not set in .env")

    creds = base64.b64encode(f"{c.DASHBOARD_USERNAME}:{c.DASHBOARD_PASSWORD}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url} with valid credentials")

    return f"{url} -> 401 without auth, 200 with valid credentials"


def check_telegram():
    import requests
    import config_loader as c
    if not c.TELEGRAM_ENABLED:
        return "disabled in config.yaml, skipping"
    if not c.TELEGRAM_BOT_TOKEN or not c.TELEGRAM_CHAT_ID:
        raise RuntimeError("telegram.enabled=true but TELEGRAM_BOT_TOKEN/CHAT_ID missing from .env")
    r = requests.get(f"https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/getMe", timeout=10)
    if not r.ok or not r.json().get("ok"):
        raise RuntimeError(f"getMe failed: HTTP {r.status_code} {r.text[:200]}")
    r2 = requests.get(
        f"https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/getChat",
        params={"chat_id": c.TELEGRAM_CHAT_ID},
        timeout=10,
    )
    if not r2.ok or not r2.json().get("ok"):
        raise RuntimeError(f"getChat failed for configured chat id: HTTP {r2.status_code} {r2.text[:200]}")
    return "bot token + chat id valid"


def check_ffmpeg():
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found on PATH (needed by OpenCV's FFMPEG backend)")
    return shutil.which("ffprobe")


def main():
    print("== Surveillance pipeline health check ==\n")

    check("config.yaml / .env load", check_config)
    check("python dependencies importable", check_imports)
    check("ffmpeg/ffprobe available", check_ffmpeg)
    check("known_faces has usable data", check_known_faces)
    check("faces.db schema", check_db)
    check("camera-rtsp active", check_camera_rtsp_service)
    check("sur-recognize.service active", check_recognize_service)
    check("sur-dashboard.service active", check_dashboard_service)
    check("RTSP stream readable", check_rtsp_stream)
    check("dashboard HTTP API responds", check_dashboard_http)
    warn("Telegram bot reachable", check_telegram)

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {', '.join(failures)}")
        sys.exit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()
