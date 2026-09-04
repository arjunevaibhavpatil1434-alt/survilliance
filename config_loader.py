"""Shared config loader for the surveillance pipeline.

Every script pulls its settings from config.yaml (paths, ports, tuning) and
.env (secrets) through this module instead of hardcoding them, so there's
one place to change e.g. the RTSP URL or the camera's IP.
"""

import os

import yaml
from dotenv import load_dotenv

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")

load_dotenv(os.path.join(CONFIG_DIR, ".env"))

with open(CONFIG_FILE, "r") as f:
    _config = yaml.safe_load(f)


def get(*keys, default=None):
    node = _config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


BASE_DIR = get("paths", "base_dir", default=CONFIG_DIR)
KNOWN_FACES_DIR = os.path.join(BASE_DIR, get("paths", "known_faces_dir", default="known_faces"))
UNKNOWN_FACES_DIR = os.path.join(BASE_DIR, get("paths", "unknown_faces_dir", default="unknown_faces"))
LOGS_DIR = os.path.join(BASE_DIR, get("paths", "logs_dir", default="logs"))
DB_FILE = os.path.join(BASE_DIR, get("paths", "db_file", default="faces.db"))
LOG_FILE = os.path.join(LOGS_DIR, "events.log")

RTSP_HOST = get("stream", "rtsp_host", default="127.0.0.1")
RTSP_PORT = get("stream", "rtsp_port", default=8554)
RTSP_PATH = get("stream", "path", default="cam01")
RTSP_URL = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{RTSP_PATH}"

CAMERA_SOURCE_IP = get("camera", "source_ip")

COOLDOWN_SECONDS = get("recognition", "cooldown_seconds", default=30)
FACE_TOLERANCE = get("recognition", "tolerance", default=0.55)

DASHBOARD_HOST = get("dashboard", "host", default="0.0.0.0")
DASHBOARD_PORT = get("dashboard", "port", default=8080)

TELEGRAM_ENABLED = get("telegram", "enabled", default=True)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# TELEGRAM_CHAT_ID accepts one ID or a comma-separated list, so a single
# .env value can notify multiple people/groups - see notify.py, which
# sends to all of them. TELEGRAM_CHAT_ID itself stays the first one for
# healthcheck.py's single-chat getChat probe.
TELEGRAM_CHAT_IDS = [
    chat_id.strip()
    for chat_id in (os.getenv("TELEGRAM_CHAT_ID") or "").split(",")
    if chat_id.strip()
]
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else None

DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
