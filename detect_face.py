import cv2
import face_recognition
import subprocess
import os

known_encodings = []

folder = "/home/server/faces/Saikrishna"

for f in os.listdir(folder):
    path = os.path.join(folder, f)

    if not f.endswith((".png", ".jpg", ".jpeg")):
        continue

    img = face_recognition.load_image_file(path)
    enc = face_recognition.face_encodings(img)

    if enc:
        known_encodings.append(enc[0])

print("Loaded", len(known_encodings), "face images")

cap = cv2.VideoCapture("udp://127.0.0.1:5004")

announced = False

while True:
    ret, frame = cap.read()

    if not ret:
        continue

    rgb = frame[:, :, ::-1]

    faces = face_recognition.face_encodings(rgb)

    for face in faces:

        match = face_recognition.compare_faces(
            known_encodings,
            face,
            tolerance=0.5
        )

        if True in match and not announced:
            print("Detected: Saikrishna")

            subprocess.Popen(
                ["espeak", "Welcome Saikrishna"]
            )

            announced = True

    cv2.imshow("Recognition", frame)

    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()
