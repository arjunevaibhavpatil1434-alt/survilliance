import csv
import io
import os
import secrets
import sys
import sqlite3

# OpenCV's FFmpeg RTSP reader buffers frames internally by default; if
# gen_frames() below ever falls a beat behind the incoming stream, that
# buffer doesn't drain, so the feed drifts further and further behind
# real time the longer it stays open. These flags tell the FFmpeg
# demuxer not to buffer and to always decode/deliver the newest frame
# available - must be set before cv2 (and its bundled FFmpeg) is used.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0",
)

import cv2
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import (
    RTSP_URL,
    DB_FILE as DB_PATH,
    LOG_FILE,
    UNKNOWN_FACES_DIR as UNKNOWN_DIR,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_USERNAME,
    DASHBOARD_PASSWORD,
)

app = Flask(__name__)

if not DASHBOARD_USERNAME or not DASHBOARD_PASSWORD:
    raise RuntimeError(
        "DASHBOARD_USERNAME / DASHBOARD_PASSWORD are not set in .env - "
        "the dashboard refuses to start without auth credentials configured."
    )


@app.before_request
def require_auth():
    auth = request.authorization
    valid = (
        auth is not None
        and secrets.compare_digest(auth.username, DASHBOARD_USERNAME)
        and secrets.compare_digest(auth.password, DASHBOARD_PASSWORD)
    )
    if not valid:
        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="Surveillance Dashboard"'}
        )


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT,
            event_type TEXT NOT NULL,
            image_path TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


ensure_schema()


def gen_frames():
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        return

    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                continue

            ok, buffer = cv2.imencode(".jpg", frame)

            if not ok:
                continue

            frame_bytes = buffer.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
    finally:
        cap.release()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(
        gen_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/api/current_face")
def api_current_face():
    conn = get_db_connection()

    row = conn.execute(
        "SELECT person_name, event_type, image_path, timestamp "
        "FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()

    conn.close()

    if row is None:
        return jsonify({
            "person_name": None,
            "event_type": None,
            "image_path": None,
            "timestamp": None
        })

    return jsonify(dict(row))


@app.route("/api/events")
def api_events():
    conn = get_db_connection()

    rows = conn.execute(
        "SELECT id, person_name, event_type, image_path, timestamp "
        "FROM events ORDER BY id DESC LIMIT 50"
    ).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.route("/api/logs")
def api_logs():
    if not os.path.exists(LOG_FILE):
        return jsonify([])

    with open(LOG_FILE, "r") as f:
        lines = f.readlines()

    last_lines = [line.strip() for line in lines[-100:]]
    last_lines.reverse()

    return jsonify(last_lines)


@app.route("/api/unknown_faces")
def api_unknown_faces():
    if not os.path.isdir(UNKNOWN_DIR):
        return jsonify([])

    files = [
        f for f in os.listdir(UNKNOWN_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    # Filenames aren't sortable as strings - some are unix timestamps
    # (unknown_<epoch>.jpg, from recognize_rtsp.py) and at least one is a
    # leftover unknown_YYYYMMDD_HHMMSS.jpg from an older script, so sort by
    # actual mtime instead or a name like unknown_2026... permanently
    # outsorts every newer unknown_17888... unix-timestamp file.
    files.sort(
        key=lambda f: os.path.getmtime(os.path.join(UNKNOWN_DIR, f)),
        reverse=True,
    )

    return jsonify(files)


@app.route("/unknown_faces/<path:filename>")
def unknown_face_file(filename):
    return send_from_directory(UNKNOWN_DIR, filename)


@app.route("/attendance")
def attendance_page():
    return render_template("attendance.html")


@app.route("/api/attendance")
def api_attendance():
    date_filter = request.args.get("date")
    conn = get_db_connection()

    if date_filter:
        rows = conn.execute(
            """
            SELECT id, person_name, date, time, timestamp
            FROM attendance
            WHERE date = ?
            ORDER BY timestamp DESC
            """,
            (date_filter,)
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, person_name, date, time, timestamp
            FROM attendance
            ORDER BY timestamp DESC
            LIMIT 200
            """
        ).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.route("/attendance/export.csv")
def export_attendance_csv():
    date_filter = request.args.get("date")
    conn = get_db_connection()

    if date_filter:
        rows = conn.execute(
            """
            SELECT person_name, date, time, timestamp
            FROM attendance
            WHERE date = ?
            ORDER BY timestamp
            """,
            (date_filter,)
        ).fetchall()
        filename = f"attendance_{date_filter}.csv"
    else:
        rows = conn.execute(
            """
            SELECT person_name, date, time, timestamp
            FROM attendance
            ORDER BY timestamp
            """
        ).fetchall()
        filename = "attendance_all.csv"

    conn.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Person Name", "Date", "Time", "Timestamp"])

    for row in rows:
        writer.writerow([row["person_name"], row["date"], row["time"], row["timestamp"]])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
