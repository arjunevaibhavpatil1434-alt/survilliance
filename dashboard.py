from flask import Flask, Response
import sqlite3
import cv2

from config_loader import RTSP_URL, DB_FILE, DASHBOARD_HOST, DASHBOARD_PORT

app = Flask(__name__)


def generate_frames():

    print("Opening RTSP stream...")

    cap = cv2.VideoCapture(
        RTSP_URL,
        cv2.CAP_FFMPEG
    )

    print("Opened:", cap.isOpened())

    while True:

        success, frame = cap.read()

        if not success:
            continue

        ret, buffer = cv2.imencode(".jpg", frame)

        if not ret:
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' +
            frame_bytes +
            b'\r\n'
        )


@app.route("/video")
def video():

    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/")
def home():

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance")
    total_attendance = cursor.fetchone()[0]

    cursor.execute("""
        SELECT person_name,event_type,timestamp
        FROM events
        ORDER BY id DESC
        LIMIT 10
    """)

    events = cursor.fetchall()

    cursor.execute("""
        SELECT person_name,date,time
        FROM attendance
        ORDER BY id DESC
        LIMIT 10
    """)

    attendance = cursor.fetchall()

    conn.close()

    recent_events = ""

    for row in events:
        recent_events += (
            f"<tr>"
            f"<td>{row[0]}</td>"
            f"<td>{row[1]}</td>"
            f"<td>{row[2]}</td>"
            f"</tr>"
        )

    attendance_rows = ""

    for row in attendance:
        attendance_rows += (
            f"<tr>"
            f"<td>{row[0]}</td>"
            f"<td>{row[1]}</td>"
            f"<td>{row[2]}</td>"
            f"</tr>"
        )

    return f"""
<!DOCTYPE html>
<html>
<head>

<title>AI Surveillance Dashboard</title>

<style>

body {{
    font-family: Arial, sans-serif;
    background: #f2f2f2;
    margin: 0;
    padding: 10px;
}}

h1 {{
    text-align: center;
}}

.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}}

.panel {{
    background: white;
    border-radius: 10px;
    padding: 15px;
    min-height: 350px;
    box-shadow: 0px 0px 5px gray;
}}

.video {{
    width: 100%;
    border-radius: 8px;
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

th, td {{
    border: 1px solid #ccc;
    padding: 5px;
}}

</style>

</head>

<body>

<h1>AI Surveillance Dashboard</h1>

<div class="grid">

    <div class="panel">
        <h2>Live Camera Feed</h2>

        <img class="video" src="/video" alt="Live camera stream">
    </div>

    <div class="panel">
        <h2>Statistics</h2>

        <h3>Total Events: {total_events}</h3>

        <h3>Total Attendance: {total_attendance}</h3>
    </div>

    <div class="panel">
        <h2>Recent Events</h2>

        <table>
            <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Timestamp</th>
            </tr>

            {recent_events}

        </table>
    </div>

    <div class="panel">
        <h2>Recent Attendance</h2>

        <table>
            <tr>
                <th>Name</th>
                <th>Date</th>
                <th>Time</th>
            </tr>

            {attendance_rows}

        </table>
    </div>

</div>

</body>
</html>
"""


if __name__ == "__main__":
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
