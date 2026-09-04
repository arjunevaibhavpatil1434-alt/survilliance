import os
import time
import cv2
import face_recognition

RTSP_URL = "rtsp://192.168.88.249:8554/cam01"

KNOWN_FACE_DIR = "faces/Saikrishna"

KNOWN_DIR = "captures"
UNKNOWN_DIR = "unknown_faces"
LOG_DIR = "logs"

ATTENDANCE_LOG = "logs/attendance.log"

THRESHOLD = 0.65
MATCHES_REQUIRED = 3

KNOWN_COOLDOWN = 60
UNKNOWN_COOLDOWN = 60

PI_IP = "192.168.88.153"

KNOWN_AUDIO = "/home/root/hello_saikrishna.wav"
UNKNOWN_AUDIO = "/home/root/unknown_person.wav"

os.makedirs(KNOWN_DIR, exist_ok=True)
os.makedirs(UNKNOWN_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

known_encodings = []

print("Loading known faces...")

for filename in os.listdir(KNOWN_FACE_DIR):

    if not filename.lower().endswith(
        (".jpg", ".jpeg", ".png")
    ):
        continue

    filepath = os.path.join(
        KNOWN_FACE_DIR,
        filename
    )

    try:

        image = face_recognition.load_image_file(
            filepath
        )

        encodings = face_recognition.face_encodings(
            image
        )

        if len(encodings) > 0:

            known_encodings.append(
                encodings[0]
            )

            print(
                f"Loaded: {filename}"
            )

    except Exception as e:

        print(
            f"Failed loading {filename}: {e}"
        )

if len(known_encodings) == 0:

    print("No valid known faces found")
    exit()

print(
    f"Known faces loaded: {len(known_encodings)}"
)

cap = cv2.VideoCapture(
    RTSP_URL,
    cv2.CAP_FFMPEG
)

if not cap.isOpened():

    print("RTSP failed")
    exit()

print("RTSP connected")

last_known_greet = 0
last_unknown_greet = 0

consecutive_matches = 0

while True:

    ret, frame = cap.read()

    if not ret:
        continue

    small = cv2.resize(
        frame,
        (0, 0),
        fx=0.5,
        fy=0.5
    )

    rgb = cv2.cvtColor(
        small,
        cv2.COLOR_BGR2RGB
    )

    locations = face_recognition.face_locations(
        rgb
    )

    if len(locations) == 0:

        consecutive_matches = 0
        continue

    encodings = face_recognition.face_encodings(
        rgb,
        locations
    )

    for encoding in encodings:

        distances = face_recognition.face_distance(
            known_encodings,
            encoding
        )

        min_distance = min(distances)

        print(
            f"Distance: {min_distance:.3f}"
        )

        if min_distance < THRESHOLD:

            consecutive_matches = min(
                consecutive_matches + 1,
                MATCHES_REQUIRED
            )

            print(
                f"Match {consecutive_matches}/{MATCHES_REQUIRED}"
            )

            if (
                consecutive_matches >= MATCHES_REQUIRED
                and
                time.time() - last_known_greet >
                KNOWN_COOLDOWN
            ):

                detection_time = time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                filename_time = time.strftime(
                    "%Y%m%d_%H%M%S"
                )

                print(
                    f"Hello Saikrishna - Detected at {detection_time}"
                )

                image_file = (
                    f"{KNOWN_DIR}/"
                    f"Saikrishna_{filename_time}.jpg"
                )

                cv2.imwrite(
                    image_file,
                    frame
                )

                with open(
                    ATTENDANCE_LOG,
                    "a"
                ) as log:

                    log.write(
                        f"{detection_time} : Saikrishna\n"
                    )

                os.system(
                    f'ssh root@{PI_IP} '
                    f'"aplay -D plughw:3,0 {KNOWN_AUDIO}"'
                )

                last_known_greet = time.time()

                consecutive_matches = 0

        else:

            consecutive_matches = 0

            detection_time = time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            filename_time = time.strftime(
                "%Y%m%d_%H%M%S"
            )

            print(
                f"Unknown Person - Detected at {detection_time}"
            )

            cv2.imwrite(
                f"{UNKNOWN_DIR}/unknown_{filename_time}.jpg",
                frame
            )

            if (
                time.time() - last_unknown_greet >
                UNKNOWN_COOLDOWN
            ):

                os.system(
                    f'ssh root@{PI_IP} '
                    f'"aplay -D plughw:3,0 {UNKNOWN_AUDIO}"'
                )

                print(
                    f"Unknown visitor detected at {detection_time}"
                )

             
