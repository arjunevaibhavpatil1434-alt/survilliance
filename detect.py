from ultralytics import YOLO
import cv2
import time

model = YOLO("yolov8n.pt")

url = "rtsp://127.0.0.1:8554/cam01"

cap = cv2.VideoCapture(url)

while True:

    ret, frame = cap.read()

    if not ret:
        print("No frame")
        time.sleep(1)
        continue

    results = model(frame)

    boxes = results[0].boxes

    for box in boxes:

        cls = int(box.cls[0])
        conf = float(box.conf[0])

        name = model.names[cls]

        print(
            f"Detected: {name} "
            f"Confidence: {conf:.2f}"
        )

    time.sleep(0.1)
