from ultralytics import YOLO
import cv2
import subprocess
import time

model = YOLO("yolov8n.pt")

cap = cv2.VideoCapture("udp://127.0.0.1:5006")

print("Camera opened:", cap.isOpened())

last_announcement = 0

while True:
    ret, frame = cap.read()

    if not ret:
        continue

    results = model(frame, verbose=False)

    for r in results:
        for box in r.boxes:

            cls = int(box.cls[0])

            if model.names[cls] == "person":

                now = time.time()

                if now - last_announcement > 20:
                    print("Person detected")

                    subprocess.Popen(
                        ["espeak", "Person detected"]
                    )

                    last_announcement = now

    if cv2.waitKey(1) == 27:
        break

cap.release()
