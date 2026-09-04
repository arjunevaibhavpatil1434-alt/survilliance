import cv2
import face_recognition
import os
import subprocess

known_encodings = []
known_names = []

base_dir = "/home/server/faces"

for person in os.listdir(base_dir):

    person_dir = os.path.join(base_dir, person)

    if not os.path.isdir(person_dir):
        continue

    for img_file in os.listdir(person_dir):

        if not img_file.lower().endswith((".png",".jpg",".jpeg")):
            continue

        path = os.path.join(person_dir, img_file)

        img = face_recognition.load_image_file(path)
        enc = face_recognition.face_encodings(img)

        if enc:
            known_encodings.append(enc[0])
            known_names.append(person)

            print("Loaded:", person, img_file)

print("Total encodings:", len(known_encodings))

cap = cv2.VideoCapture("udp://127.0.0.1:5006")


last_name = None

while True:

    ret, frame = cap.read()

    if not ret:
        continue

    rgb = frame[:, :, ::-1]

    locations = face_recognition.face_locations(rgb)
    encodings = face_recognition.face_encodings(rgb, locations)

    for face in encodings:

        matches = face_recognition.compare_faces(
            known_encodings,
            face,
            tolerance=0.5
        )

        if True in matches:

            name = known_names[matches.index(True)]

            if name != last_name:

                print("Detected:", name)

                subprocess.Popen(
                    ["espeak", f"Welcome {name}"]
                )

                last_name = name

    cv2.imshow("Recognition", frame)

    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()
