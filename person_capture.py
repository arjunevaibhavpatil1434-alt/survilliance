from ultralytics import YOLO
import cv2
import time
from datetime import datetime
import os

os.makedirs("captures", exist_ok=True)

model = YOLO("yolov8n.pt")

cap = cv2.VideoCapture(
    "rtsp://192.168.88.249:8554/cam01"
)

last_save = 0

while True:

    ret, frame = cap.read()

    if not ret:
        continue

    results = model(frame, verbose=False)

    person_found = False

    for box in results[0].boxes:

        cls = int(box.cls)

        if model.names[cls] == "person":

            person_found = True
            break

    if person_found and time.time() - last_save > 10:

        filename = (
            "captures/person_" +
            datetime.now().strftime("%Y%m%d_%H%M%S") +
            ".jpg"
        )

        cv2.imwrite(filename, frame)

        print("Saved:", filename)

        last_save = time.time()
