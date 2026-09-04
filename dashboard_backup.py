from flask import Flask, Response
import cv2

app = Flask(__name__)

RTSP_URL = "rtsp://127.0.0.1:8554/cam01"

def generate_frames():

    print("Opening RTSP stream...")

    cap = cv2.VideoCapture(
        RTSP_URL,
        cv2.CAP_FFMPEG
    )

    print("Opened:", cap.isOpened())

    while True:

        success, frame = cap.read()

        print("Frame:", success)

        if not success:
            continue

        ret, buffer = cv2.imencode(
            ".jpg",
            frame
        )

        if not ret:
            continue

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n'
            + buffer.tobytes()
            + b'\r\n'
        )

@app.route("/video")
def video():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/")
def home():
    html = ""
    html += "<html>"
    html += "<head><title>Live Feed</title></head>"
    html += "<body>"
    html += "<h1>Live Camera Feed</h1>"
    html += "/video"
    html += "</body>"
    html += "</html>"
    return html


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )
