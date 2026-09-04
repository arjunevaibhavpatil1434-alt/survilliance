import cv2

name = input("Enter name: ")

cap = cv2.VideoCapture(0)  # local webcam

while True:
    ret, frame = cap.read()

    if not ret:
        continue

    cv2.imshow("Capture Face", frame)

    key = cv2.waitKey(1)

    if key == ord('s'):
        cv2.imwrite(f"/home/server/faces/{name}.jpg", frame)
        print(f"Saved /home/server/faces/{name}.jpg")
        break

cap.release()
cv2.destroyAllWindows()

