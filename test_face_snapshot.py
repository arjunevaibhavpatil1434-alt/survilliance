import cv2

cap = cv2.VideoCapture("rtsp://192.168.88.249:8554/cam01")

ret, frame = cap.read()

if ret:
    cv2.imwrite("snapshot.jpg", frame)
    print("Saved snapshot.jpg")
else:
    print("Failed")
