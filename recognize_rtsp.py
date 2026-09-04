import os

# OpenCV's FFmpeg RTSP reader buffers frames internally by default; since
# this loop does real work (YOLO + Haar + face_recognition) per frame, any
# time a frame takes longer than the source's frame interval, that buffer
# doesn't drain, and detection keeps falling further behind live video the
# longer the process runs. These flags tell the FFmpeg demuxer not to
# buffer and to always hand back the newest frame - must be set before cv2
# (and its bundled FFmpeg) is used.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0",
)

import cv2
import face_recognition
import sqlite3
import time
from datetime import datetime

# This CPU doesn't support NNPACK, and torch's C++ layer logs a "Could not
# initialize NNPACK" warning on every conv2d call in YOLO's forward pass
# (it still falls back to a different backend fine) - must be set before
# torch's native lib loads, or it floods sur-recognize.log at ~20/sec.
os.environ.setdefault("TORCH_CPP_LOG_LEVEL", "ERROR")

from ultralytics import YOLO
import torch

torch.backends.nnpack.enabled = False

from notify import send_message, send_photo
from greet_stream import greet_known, greet_unknown
from config_loader import (
    RTSP_URL,
    BASE_DIR,
    KNOWN_FACES_DIR as KNOWN_DIR,
    UNKNOWN_FACES_DIR as UNKNOWN_DIR,
    LOGS_DIR as LOG_DIR,
    DB_FILE,
    LOG_FILE,
    COOLDOWN_SECONDS as COOLDOWN,
    FACE_TOLERANCE,
)

# ======================================
# CONFIGURATION
# ======================================
# RTSP_URL, paths and tuning now come from config.yaml via config_loader.

# ======================================
# CREATE DIRECTORIES
# ======================================

os.makedirs(UNKNOWN_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ======================================
# DATABASE
# ======================================

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

# The dashboard also creates these tables on startup, but this service must
# not depend on start order (it can run standalone or restart independently).
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_name TEXT,
        event_type TEXT NOT NULL,
        image_path TEXT,
        timestamp TEXT NOT NULL
    )
    """
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_name TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        timestamp TEXT NOT NULL
    )
    """
)

conn.commit()

# ======================================
# FUNCTIONS
# ======================================

def write_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def save_event(person_name, event_type, image_path=None):

    cursor.execute(
        """
        INSERT INTO events
        (
            person_name,
            event_type,
            image_path,
            timestamp
        )
        VALUES
        (
            ?,
            ?,
            ?,
            datetime('now')
        )
        """,
        (
            person_name,
            event_type,
            image_path
        )
    )

    conn.commit()


def save_attendance(person_name):

    cursor.execute(
        """
        INSERT INTO attendance
        (
            person_name,
            date,
            time,
            timestamp
        )
        VALUES
        (
            ?,
            date('now'),
            time('now'),
            datetime('now')
        )
        """,
        (person_name,)
    )

    conn.commit()

# ======================================
# LOAD KNOWN FACES
# ======================================

print("Loading known faces...")

known_encodings = []
known_names = []

for person in os.listdir(KNOWN_DIR):

    person_dir = os.path.join(KNOWN_DIR, person)

    if not os.path.isdir(person_dir):
        continue

    for image_file in os.listdir(person_dir):

        image_path = os.path.join(
            person_dir,
            image_file
        )

        try:

            image = face_recognition.load_image_file(
                image_path
            )

            encodings = face_recognition.face_encodings(
                image
            )

            if len(encodings) > 0:

                known_encodings.append(
                    encodings[0]
                )

                known_names.append(
                    person
                )

                print(f"Loaded: {image_file}")

        except Exception as e:

            print(
                f"Error loading {image_file}: {e}"
            )

print(
    f"\nLoaded {len(known_encodings)} known face(s)\n"
)

# ======================================
# FACE DETECTOR
# ======================================


def _find_haarcascade():
    # The pip opencv-python wheel bundles cv2.data.haarcascades, but
    # system-packaged builds of opencv (e.g. this board's Yocto image)
    # don't - fall back to the OS-installed copy.
    if hasattr(cv2, "data"):
        return os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")

    for candidate in (
        "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
        "/usr/share/OpenCV/haarcascades/haarcascade_frontalface_default.xml",
    ):
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError("haarcascade_frontalface_default.xml not found")


face_cascade = cv2.CascadeClassifier(_find_haarcascade())

# ======================================
# PERSON DETECTOR (YOLO pre-filter)
# ======================================
# Stock COCO-pretrained yolov8n.pt (no CUDA on this box, runs on CPU) - it
# has no "face" class, so it's used to find person boxes first and narrow
# the Haar cascade + face_recognition work below to those regions instead
# of the full frame. Cuts both false positives from background clutter and
# wasted encoding calls when nobody's in frame at all.
YOLO_MODEL_PATH = os.path.join(BASE_DIR, "yolov8n.pt")
YOLO_PERSON_CLASS = 0
YOLO_CONF_THRESHOLD = 0.4

yolo_model = YOLO(YOLO_MODEL_PATH)

# ======================================
# RTSP STREAM
# ======================================

RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60


def connect_stream():
    """Block until the RTSP stream is reachable, retrying with backoff.

    The camera publisher can go offline independently of this service
    (network hiccup, camera reboot, etc). Retrying here instead of
    exiting keeps systemd from crash-looping and reloading known faces
    on every restart attempt.
    """

    delay = RECONNECT_DELAY

    while True:

        cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        time.sleep(2)

        if cap.isOpened():

            ret, _ = cap.read()

            if ret:
                print("Connected to RTSP stream")
                return cap

        cap.release()

        print(f"RTSP stream unavailable, retrying in {delay}s...")

        time.sleep(delay)

        delay = min(delay * 2, MAX_RECONNECT_DELAY)


cap = connect_stream()

# ======================================
# TRACKING
# ======================================

last_seen = {}
last_unknown_time = 0
consecutive_read_failures = 0
MAX_CONSECUTIVE_FAILURES = 60

# ======================================
# MAIN LOOP
# ======================================

while True:

    ret, frame = cap.read()

    if not ret:

        consecutive_read_failures += 1

        if consecutive_read_failures >= MAX_CONSECUTIVE_FAILURES:
            print("Stream appears to have dropped, reconnecting...")
            cap.release()
            cap = connect_stream()
            consecutive_read_failures = 0

        continue

    consecutive_read_failures = 0

    yolo_result = yolo_model(
        frame,
        classes=[YOLO_PERSON_CLASS],
        conf=YOLO_CONF_THRESHOLD,
        verbose=False,
    )[0]

    person_boxes = [
        tuple(int(v) for v in box.xyxy[0].tolist())
        for box in yolo_result.boxes
    ]

    if not person_boxes:
        continue

    for (px1, py1, px2, py2) in person_boxes:

        person_crop = frame[py1:py2, px1:px2]

        if person_crop.size == 0:
            continue

        gray = cv2.cvtColor(
            person_crop,
            cv2.COLOR_BGR2GRAY
        )

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60)
        )

        for (x, y, w, h) in faces:

            # Offsets are relative to person_crop - map back to frame
            # coordinates so saved/logged images use the full frame.
            fx, fy = px1 + x, py1 + y

            face_img = frame[
                fy:fy+h,
                fx:fx+w
            ]

            rgb_face = cv2.cvtColor(
                face_img,
                cv2.COLOR_BGR2RGB
            )

            encodings = face_recognition.face_encodings(
                rgb_face
            )

            if len(encodings) == 0:
                continue

            face_encoding = encodings[0]

            matches = face_recognition.compare_faces(
                known_encodings,
                face_encoding,
                tolerance=FACE_TOLERANCE
            )

            current_time = time.time()

            # ==========================
            # KNOWN FACE
            # ==========================

            if True in matches:

                idx = matches.index(True)

                name = known_names[idx]

                if (
                    name not in last_seen
                    or current_time - last_seen[name] > COOLDOWN
                ):

                    print(f"Known Face: {name}")

                    write_log(
                        f"KNOWN FACE: {name}"
                    )

                    save_event(
                        name,
                        "KNOWN"
                    )

                    save_attendance(
                        name
                    )

                    try:
                        send_message(
                            f"✅ Known Face Detected\nName: {name}"
                        )
                    except Exception as e:
                        print(
                            f"Telegram error: {e}"
                        )

                    greet_known(name)

                    last_seen[name] = current_time

            # ==========================
            # UNKNOWN FACE
            # ==========================

            else:

                if (
                    current_time - last_unknown_time > COOLDOWN
                ):

                    filename = os.path.join(
                        UNKNOWN_DIR,
                        f"unknown_{int(current_time)}.jpg"
                    )

                    cv2.imwrite(
                        filename,
                        frame
                    )

                    print("Unknown Face")

                    write_log(
                        f"UNKNOWN FACE: {filename}"
                    )

                    save_event(
                        "Unknown",
                        "UNKNOWN",
                        filename
                    )

                    try:

                        send_message(
                            "⚠ Unknown Person Detected"
                        )

                        send_photo(
                            filename
                        )

                    except Exception as e:

                        print(
                            f"Telegram error: {e}"
                        )

                    greet_unknown()

                    last_unknown_time = current_time
