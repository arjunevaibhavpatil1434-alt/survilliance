from ultralytics import YOLO
import cv2

model = YOLO("yolov8n.pt")

cap = cv2.VideoCapture(
    "rtsp://192.168.88.249:8554/cam01"
)

while True:

    ret, frame = cap.read()

    if not ret:
        continue

    results = model(frame, verbose=False)

    for box in results[0].boxes:

        cls = int(box.cls)
        conf = float(box.conf)

        print(
            f"{model.names[cls]} "
            f"{conf:.2f}"
        )
