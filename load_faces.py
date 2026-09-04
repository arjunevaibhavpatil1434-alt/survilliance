import face_recognition
import os

folder = "/home/server/faces/Saikrishna"

encodings = []

for f in sorted(os.listdir(folder)):
    path = os.path.join(folder, f)

    if not os.path.isfile(path):
        continue

    try:
        img = face_recognition.load_image_file(path)
        face_enc = face_recognition.face_encodings(img)

        if face_enc:
            encodings.append(face_enc[0])
            print(f"Loaded: {f}")
        else:
            print(f"No face found: {f}")

    except Exception as e:
        print(f"Error in {f}: {e}")

print("Total usable images:", len(encodings))
