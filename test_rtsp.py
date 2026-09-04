import cv2

cap = cv2.VideoCapture(
    "rtsp://192.168.88.249:8554/cam01",
    cv2.CAP_FFMPEG
)

print("Opened:", cap.isOpened())

for i in range(100):

    ret, frame = cap.read()

    print("Frame:", ret)

    if ret:
        print("Shape:", frame.shape)
        break

cap.release()
