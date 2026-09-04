import face_recognition

image = face_recognition.load_image_file(
    "known_faces/saikrishna.jpg"
)

faces = face_recognition.face_encodings(image)

print("Faces Found:", len(faces))
