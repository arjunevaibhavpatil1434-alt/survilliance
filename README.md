# Surveillance pipeline

Face-recognition surveillance system: an RPi4 camera publishes H.264+AAC
over RTSP to a server, which records it, runs YOLO + face_recognition on
the live feed, serves a dashboard, and sends Telegram alerts and live
voice greetings.

## Architecture

```
OV5647 camera + USB mic (RPi4)
  -> rpicam-vid (raw YUV420) | ffmpeg (libx264 + AAC, mixes in
     greet_audio_feeder.py's greeting channel via amix)
  -> RTSP -> mediamtx (server)
       -> recording (segmented fMP4, /srv/camera_recordings)
       -> recognize_rtsp.py: YOLO (person pre-filter) -> Haar cascade
          (face detection) -> face_recognition (encoding/match)
            -> known: log + Telegram + greet_stream.py ("Hello, <name>",
               mixed live into the RTSP stream via greet_audio_feeder.py)
            -> unknown: save capture + log + Telegram + greet_stream.py
               ("No match")
       -> dashboard/app.py: live feed, event log, unknown-face gallery,
          known/unknown status, attendance export
telegram_bot.py: lets people self-register for alerts from their phone
  (/start to a Telegram bot) instead of an admin editing .env by hand
```

The RPi is input-only - camera capture and greeting playback. Everything
else (mediamtx, recording, recognition, dashboard, Telegram) runs on the
server.

## What runs where

**RPi4** (`initd/` - this board has no systemd, plain sysvinit):
- `camera_rtsp_server.py` (`initd/camera-rtsp`) - captures + publishes to
  the server's mediamtx
- `greet_audio_feeder.py` (`initd/greet-audio-feeder`) - feeds the live
  greeting audio channel that `camera_rtsp_server.py`'s ffmpeg mixes in

**Server** (real systemd, unit files not included here - see below):
- `mediamtx` (external binary, not in this repo) - RTSP relay + recording,
  config: `mediamtx.yml` (template - the deployed copy has a real
  `PUBLIC_RTSP_PASSWORD`, not the placeholder here)
- `recognize_rtsp.py` (`sur-recognize.service`) - detection pipeline
- `dashboard/app.py` (`sur-dashboard.service`) - web dashboard, port 8080
- `telegram_bot.py` (`sur-telegram-bot.service`) - self-registration bot

Server systemd units aren't checked in (they're trivial - `Type=simple`,
`Restart=always`, `WorkingDirectory=/home/server/sur-floders`,
`ExecStart=/usr/bin/python3 <script>`); recreate them from that pattern
if redeploying from scratch.

## Setup

1. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID` (comma-separated for multiple recipients),
   `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`.
2. Adjust `config.yaml` (paths, RTSP host/port, recognition tuning).
3. `pip install -r requirements.txt` (server) and
   `pip install -r dashboard/requirements.txt` (dashboard).
4. Populate `known_faces/<name>/*.jpg` with reference photos per person
   (not checked into this repo - see `.gitignore`).
5. `yolov8n.pt` (stock Ultralytics COCO weights, ~6.5MB, not checked in)
   downloads automatically on first `YOLO("yolov8n.pt")` call, or fetch it
   manually from Ultralytics.
6. Deploy `mediamtx.yml` to wherever mediamtx reads its config from (not
   this repo - see "What runs where" above), filling in
   `PUBLIC_RTSP_PASSWORD` if exposing the stream beyond your LAN/VPN.

## Not in this repo

`known_faces/`, `unknown_faces/`, `captures/`, `attendance_exports/`,
`logs/`, `faces.db` - real people's photos and detection history. See
`.gitignore`.
