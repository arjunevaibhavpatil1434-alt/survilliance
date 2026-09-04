from ultralytics import YOLO
import cv2
import time
from datetime import datetime

RTSP_URL = "rtsp://YOUR_SERVER_IP:8554/webcam"

person_model = YOLO("yolov8n.pt")

face_detector = cv2.CascadeClassifier(
    cv2.data.haarcascades +
    "haarcascade_frontalface_default.xml"
)

cap = cv2.VideoCapture(RTSP_URL)

last_save = 0

while True:
    ret, frame = cap.read()

    if not ret:
        continue

    results = person_model(frame)

    for box in results[0].boxes:

        cls = int(box.cls)

        if person_model.names[cls] == "person":

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            roi = frame[y1:y2, x1:x2]

            gray = cv2.cvtColor(
                roi,
                cv2.COLOR_BGR2GRAY
            )

            faces = face_detector.detectMultiScale(
                gray,
                1.1,
                4
            )

            for (fx, fy, fw, fh) in faces:

                if time.time() - last_save > 5:

                    face = roi[
                        fy:fy+fh,
                        fx:fx+fw
                    ]

                    filename = (
                        "face_" +
                        datetime.now().strftime("%Y%m%d_%H%M%S") +
                        ".jpg"
                    )

                    cv2.imwrite(filename, face)

                    print(
                        f"Saved: {filename}"
                    )

                    last_save = time.time()

    cv2.imshow(
        "AI Surveillance",
        results[0].plot()
    )

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
