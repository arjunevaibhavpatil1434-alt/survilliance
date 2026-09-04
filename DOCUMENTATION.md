# Surveillance Pipeline — Full Documentation

Complete reference for this project: what it does, how every piece fits
together, how to build it from scratch, and how to run/operate it day to
day. See `README.md` for the short version.

---

## 1. What this is

A home surveillance system built on a Raspberry Pi 4 camera and a
separate always-on server:

- The RPi captures video (CSI camera) and audio (USB mic) and streams it
  live to the server.
- The server records it, runs face detection/recognition on the live
  feed, shows a live dashboard, sends Telegram alerts (to any number of
  people, who can self-register from their phone), and plays a spoken
  greeting ("Hello, `<name>`" / "No match") mixed directly into the live
  stream's own audio track.
- The whole thing survives reboots, restarts itself on failure, watches
  its own health, and is reachable both privately (Tailscale) and
  publicly (router port-forward + DDNS), with authentication on the
  parts exposed to the internet.

## 2. Hardware

| Device | Role | Notes |
|---|---|---|
| Raspberry Pi 4 | Camera/mic input | Runs a Yocto-built embedded Linux image (sysvinit, no systemd, no package manager) |
| OV5647 CSI camera | Video source | Attached to the RPi's camera connector |
| Plantronics Blackwire 3220 (USB headset) | Audio source | Provides both the mic input and (unused for room audio - see §7.4) a speaker output; ALSA card 2, `plughw:2,0` — re-check with `arecord -l`/`aplay -l` if the hardware changes |
| Server | Everything else | A regular Linux box (this one runs Ubuntu) with `systemd`, a GPU-capable `torch` install (though no GPU is actually present here - YOLO runs on CPU), and enough disk for recordings |

## 3. Pipeline (end to end)

```
OV5647 camera ─┐
                ├─ CSI/MIPI ─ libcamera ─ rpicam-vid (raw YUV420, stdout)
USB mic ────────┘                              │
                                                │ pipe
                                                v
                                        ffmpeg (on the RPi)
                                        ├─ video: libx264 (software H.264,
                                        │  veryfast + zerolatency, 1s GOP)
                                        ├─ audio: amix(mic, greeting FIFO)
                                        │  -> AAC
                                        └─ output: RTSP (TCP) ──────┐
                                                                     │
                              greet_audio_feeder.py (RPi, Flask) ───┘
                              feeds a named pipe with silence, or a
                              posted "Hello, <name>"/"No match" clip,
                              paced to real wall-clock time so ffmpeg's
                              amix mixes it in sync with the live mic

                                                │ RTSP, over the LAN
                                                v
                                    mediamtx (server)
                                    ├─ records segmented fMP4
                                    │  (/srv/camera_recordings, 5-min
                                    │  segments, 168h retention)
                                    ├─ serves VLC / any RTSP client
                                    └─ serves recognize_rtsp.py + dashboard

                                                │
                                                v
                                    recognize_rtsp.py (server)
                                    1. cv2.VideoCapture reads a frame
                                    2. YOLOv8n finds "person" boxes
                                       (skips the frame entirely if none)
                                    3. Haar cascade finds faces inside
                                       each person box
                                    4. face_recognition encodes + compares
                                       against known_faces/
                                    5. KNOWN  -> log, save attendance,
                                       Telegram, greet_stream.py "Hello, X"
                                       UNKNOWN -> save capture, log,
                                       Telegram, greet_stream.py "No match"
                                    (cooldown: 30s per known person, 30s
                                    global for unknowns, to avoid spam)

                                                │
                                                v
                                    dashboard/app.py (Flask, server)
                                    4-panel live UI: live feed, event
                                    log, unknown-face gallery, known/
                                    unknown status - plus /attendance

telegram_bot.py (server): long-polls Telegram for /start (register) and
/stop (unregister) messages, so people can opt into alerts from their
own phone instead of an admin editing .env

stream_watchdog.py (server, timer): checks a frame is actually readable
every 3 min; after 3 consecutive failures, restarts the RPi's
camera-rtsp and sends a Telegram alert; sends a recovery message once
back
```

## 4. Repository layout

```
camera_rtsp_server.py    RPi: capture + publish (rpicam-vid | ffmpeg)
greet_audio_feeder.py    RPi: greeting-audio FIFO feeder (Flask, port 5055)
initd/                   RPi sysvinit scripts for the above two
recognize_rtsp.py        Server: detection pipeline
greet_stream.py          Server: TTS generation + posts to the RPi's feeder
notify.py                Server: Telegram sending (multi-recipient, threaded)
telegram_bot.py          Server: self-registration bot
config_loader.py         Server: loads config.yaml + .env for every script
config.yaml              Server: paths, RTSP target, tuning (not secret)
.env / .env.example      Server: secrets (Telegram token, dashboard creds)
dashboard/                Server: Flask web UI
  app.py
  templates/index.html, attendance.html
  static/css/dashboard.css
mediamtx.yml              Template for the server's mediamtx config (the
                           deployed copy, outside this repo, has real
                           secrets filled in - see §7.6)
healthcheck.py             One-shot check of the whole pipeline
stream_watchdog.py         Continuous liveness watchdog (see §3)
Makefile                   Single-command start/stop/status/verify/logs
export_attendance.py        CSV export helper
```

Not in this repo (see `.gitignore`): `known_faces/`, `unknown_faces/`,
`captures/`, `attendance_exports/`, `logs/`, `faces.db` — real people's
photos and detection history — plus `yolov8n.pt` (standard downloadable
weights) and an unrelated bundled `ai_coding_agent/` dependency tree.

## 5. Software dependencies

**RPi**: `rpicam-vid`, `ffmpeg` (built with `--enable-libx264`), Python 3
with `flask`, `numpy` (already present in this Yocto image's Python).

**Server**: Python 3 with everything in `requirements.txt` +
`dashboard/requirements.txt` (`opencv-python`, `face_recognition`,
`ultralytics`/`torch`, `flask`, `pyyaml`, `python-dotenv`, `requests`),
plus system binaries `ffmpeg`/`ffprobe`, `espeak` (TTS for greetings),
and `mediamtx` (external binary, installed separately - not a Python
package).

## 6. Building it from scratch

### 6.1. RPi side

1. Flash/boot the Yocto image, confirm the CSI camera and USB mic/headset
   are detected: `rpicam-vid --list-cameras`, `arecord -l`.
2. Confirm `ffmpeg -encoders 2>&1 | grep 264` shows `libx264` — the
   board's hardware H.264 encoder (`bcm2835-codec-encode`) fails at the
   firmware level on this image (`bcm2835_codec_start_streaming: Failed
   enabling i/p port, ret -3`) and isn't even registered in
   `v4l2-ctl --list-devices`, so software encoding via `libx264` is the
   only path — confirmed working: the board's quad Cortex-A72 keeps up
   with 1280x720@15fps in the `veryfast`/`zerolatency` preset with room
   to spare now that recognition/dashboard don't run here too.
3. Copy `camera_rtsp_server.py`, `greet_audio_feeder.py`, and
   `initd/camera-rtsp`, `initd/greet-audio-feeder` to the board (or
   `make deploy-rpi` from the server once it's set up — see §6.2).
4. Edit `camera_rtsp_server.py`'s `SERVER_HOST`/`ALSA_DEVICE` and
   `greet_audio_feeder.py`'s constants if your IPs/hardware differ from
   the defaults baked in.
5. Install the init scripts and enable at boot:
   ```
   chmod +x /etc/init.d/camera-rtsp /etc/init.d/greet-audio-feeder
   update-rc.d camera-rtsp defaults
   update-rc.d greet-audio-feeder defaults
   /etc/init.d/greet-audio-feeder start
   /etc/init.d/camera-rtsp start
   ```
   (`greet-audio-feeder` first — `camera_rtsp_server.py`'s ffmpeg opens
   the greeting FIFO as one of its inputs, and while either process can
   create the FIFO if it's missing and both retry until the other side
   shows up, starting the feeder first avoids the first startup ever
   blocking on it.)

### 6.2. Server side

1. Install `mediamtx` (download the binary, e.g. to `/opt/mediamtx/`).
2. `git clone` this repo, `make install`.
3. `cp .env.example .env`, fill in `TELEGRAM_BOT_TOKEN` (from
   [@BotFather](https://t.me/BotFather)), `TELEGRAM_CHAT_ID` (comma-
   separated for multiple people — or leave it to just the self-
   registration bot), `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`.
4. Adjust `config.yaml` if paths/ports/tuning need to differ from the
   defaults.
5. `mkdir -p known_faces/<Name>` per person, drop a few clear reference
   photos of their face in each.
6. Deploy `mediamtx.yml` to wherever your `mediamtx` install reads its
   config from, filling in a real `PUBLIC_RTSP_PASSWORD` (see §7.6 for
   what this gates).
7. `make deploy-rpi` (pushes the two RPi scripts + their init scripts
   over SSH — requires SSH key access to the RPi as root already set
   up; this project doesn't automate that first-time key exchange).
8. Create systemd units for `mediamtx`, `sur-recognize`
   (`recognize_rtsp.py`), `sur-dashboard` (`dashboard/app.py`),
   `sur-telegram-bot` (`telegram_bot.py`) — see §8.1 for the exact
   pattern — then `systemctl enable --now` each.
9. `make verify` — should show all checks passing.

### 6.3. Automation on top (optional but recommended)

- **Stream watchdog**: create `stream-watchdog.service` (`Type=oneshot`,
  runs `stream_watchdog.py`) + `stream-watchdog.timer`
  (`OnUnitActiveSec=3min`), `systemctl enable --now stream-watchdog.timer`.
- **DDNS** (only if exposing anything publicly): sign up at
  [duckdns.org](https://www.duckdns.org), get a subdomain + token, create
  a small `curl` updater script + a `systemd` timer (every 5 min) that
  calls `https://www.duckdns.org/update?domains=<sub>&token=<token>&ip=`.
- **Tailscale** (for private remote access without touching your
  router): `tailscale up` on the server and on whatever device you want
  to view the dashboard/stream from — both `mediamtx` and the dashboard
  already bind `0.0.0.0`, so they're reachable at the server's Tailscale
  IP with zero further config.
- **Public exposure** (optional, only if you want access from devices
  without Tailscale): forward TCP 8080 (dashboard) and TCP 8554 (RTSP)
  on your router to the server's LAN IP. Do this only after §7.6's
  `mediamtx` auth is in place — the stream has no protection otherwise.

## 7. How things actually work (the non-obvious parts)

### 7.1. Why RPi → H.264 via `libx264`, not the hardware encoder

Covered in §6.1 — the hardware path is firmware-broken on this specific
board/image, confirmed by both `gst-launch`'s `v4l2h264enc` and
`rpicam-vid`'s own H.264 codec option failing identically (same
underlying `bcm2835-codec` driver either way). `libx264` in software
is fully sufficient at this resolution/framerate.

### 7.2. Why YOLO runs *before* Haar/face_recognition, not instead of it

`yolov8n.pt` here is the stock Ultralytics COCO-pretrained model — it has
a `person` class, not a `face` class. `recognize_rtsp.py` uses it as a
cheap pre-filter: run YOLO on the full frame, and only run the more
expensive Haar cascade + `face_recognition` encoding inside detected
person boxes (skip the frame entirely if YOLO finds nobody). This cuts
both false positives from background clutter (Haar cascades alone are
prone to them) and wasted encoding calls when nobody's in frame.

No GPU is present on this server despite a CUDA-capable `torch` build,
so YOLO runs on CPU — measured at roughly 20 inferences/sec with no
backlog, comfortably real-time for a 15fps source.

### 7.3. Why the greeting is mixed into the *stream's* audio, not played
locally

The requirement was that anyone watching the live stream remotely hears
the greeting, not just someone standing next to the camera. Implementation:

- `greet_audio_feeder.py` (RPi) manages a named pipe (FIFO) and a Flask
  endpoint (`POST /play`, raw PCM body). It continuously writes silence
  to the FIFO, or a posted clip's bytes when one arrives.
- `camera_rtsp_server.py`'s ffmpeg command takes this FIFO as a third
  input (`-f s16le -ar 44100 -ac 1`) alongside the video and the mic, and
  mixes the mic + FIFO via `-filter_complex amix=inputs=2` into the
  audio track that actually gets encoded and sent out.
- `greet_stream.py` (server) generates "Hello, `<name>`"/"No match" with
  `espeak`, resamples to match (44100Hz mono s16le) via `ffmpeg`, and
  `POST`s the raw PCM to the RPi's feeder — off the caller's thread, so
  it doesn't block `recognize_rtsp.py`'s detection loop.

**The one non-obvious bug that had to be fixed to make this work**:
`ffmpeg`'s raw-PCM demuxer (`-f s16le`, no `-re` flag) reads as fast as
the pipe delivers data, not at real playback speed — only a genuinely
live source like ALSA capture paces itself naturally. An early version
of the feeder wrote silence in a tight, unpaced loop; `ffmpeg` raced
through a large buffered backlog of *old* silence almost instantly, so a
newly-posted clip wouldn't actually reach the live audio mix for many
seconds after being posted (confirmed by FFT-analyzing a captured stream
and finding zero trace of a posted test tone). Fixed by pacing the
feeder's writes to real wall-clock time (`time.monotonic()`-based, one
`CHUNK_SECONDS`-sized write per that much real time), so the FIFO
behaves like a genuine live source and stays in sync with the mic in
`amix`. Verified afterward via FFT: a posted 1200Hz test tone showed up
at ~85-99% of spectral energy exactly where expected in a captured
live-stream recording.

Also needed: `-thread_queue_size 1024` on all three ffmpeg inputs
(video, mic, FIFO) — the default (8) is too small for mixing two
independent live audio sources via `amix` in real time; ffmpeg's own
warning ("Thread message queue blocking; consider raising the
thread_queue_size option") names the fix directly.

### 7.4. Why the USB headset isn't just played through directly

The Plantronics Blackwire 3220 is a headset (headphones + boom mic),
not an open room speaker — even though it exposes both a playback and a
capture ALSA device, audio played to its headphone output wouldn't
reliably be picked up by its own boom mic (no meaningful acoustic
coupling), and wouldn't be audible to anyone not wearing it. Hence §7.3's
approach of mixing digitally into the outgoing stream instead of relying
on a physical speaker-to-mic loop.

### 7.5. Why `sur-recognize`/`sur-dashboard` moved off the RPi

Originally the RPi ran everything: its own RTSP server, face
recognition, and the dashboard, all on one board. This meant the board
was simultaneously the video source *and* doing all the CPU-heavy
recognition work, which under load caused the RTSP session itself to
stall (backpressure between the recognition loop's frame consumption and
the embedded RTSP server's own delivery). Splitting these across two
machines — RPi does only capture + greeting playback, the server does
everything else — removed that resource contention and let each side be
sized/tuned independently. See `git log` on `camera_rtsp_server.py`,
`recognize_rtsp.py`, and the old `initd/sur-recognize`/`initd/sur-dashboard`
scripts (kept for reference, no longer active) for the shape of the
original all-on-RPi setup.

### 7.6. mediamtx authentication

Default `mediamtx` config (no `authInternalUsers`) is wide open — any
user, any IP, every permission (publish, read, playback). Fine while
everything is LAN/Tailscale-only; not fine once a router forwards a port
to it. The deployed config (see `mediamtx.yml`'s template here) defines:

- `user: any`, no password, restricted to
  `['127.0.0.1/32', '192.168.88.0/24', '100.64.0.0/10']` (localhost, LAN,
  Tailscale's CGNAT range) — full access, matching everything that
  already needs to talk to it without credentials (the RPi's publish,
  `recognize_rtsp.py`/`dashboard.py`'s local reads, Tailscale-based
  remote access).
- `user: public`, a real password, no IP restriction, **read/playback
  only — no publish** — so a port-forwarded connection from the open
  internet can view the stream but can't inject a fake one.

### 7.7. Dashboard live-feed latency

`cv2.VideoCapture`'s FFmpeg backend buffers frames internally by
default; if a consumer (the dashboard's MJPEG re-encode loop, or
`recognize_rtsp.py`'s detection loop) ever falls a beat behind the
incoming stream, that buffer doesn't drain — the feed/detection drifts
further behind real time the longer the process stays open. Fixed in
both `dashboard/app.py` and `recognize_rtsp.py` via
`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0`
(set before `cv2` is imported) plus `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)`.

### 7.8. Multiple Telegram recipients + self-registration

`TELEGRAM_CHAT_ID` in `.env` accepts a comma-separated list
(`config_loader.py` parses it into `TELEGRAM_CHAT_IDS`).
`telegram_bot.py` long-polls Telegram's `getUpdates` API for `/start`
(register) and `/stop` (unregister) messages and stores dynamic
subscribers in a `telegram_subscribers` table in `faces.db`. `notify.py`
merges the static `.env` list with that table's contents every time it
sends, and fans out to all of them in parallel daemon threads — so one
slow/unreachable recipient's connection (up to the request timeout each)
can't delay detection of the next person, which gets worse the more
recipients there are.

### 7.9. Orphaned processes across restarts (fixed)

`camera_rtsp_server.py` runs `rpicam-vid` and `ffmpeg` as subprocesses.
`init.d`'s `stop`/`restart` sends `SIGTERM` only to the tracked Python
PID; Python's default `SIGTERM` handling kills it immediately without
running any cleanup, which orphaned `rpicam-vid`/`ffmpeg` still holding
the camera and the USB mic open — the *next* start's children then
failed to open either device (silently stuck retrying). Fixed with an
explicit `SIGTERM`/`SIGINT` handler that terminates tracked child
processes before the parent exits.

## 8. Running it day to day

### 8.1. Single-command control

From this repo, on the server (`Makefile` drives both machines):

```
make start      # bring up everything: RPi input side, then mediamtx,
                 # then sur-recognize/sur-dashboard/sur-telegram-bot
make stop       # stop everything, reverse order
make restart    # stop then start
make status     # live status of every service, both machines
make verify     # full health check (healthcheck.py) - 14 checks
make help       # full target list, including per-service logs
```

`start`/`stop`/`restart` need `sudo` on the server side (systemd) — run
as a user that has it. RPi-side targets use the existing root SSH key,
no password needed.

### 8.2. Individual services

**Server** (systemd): `mediamtx`, `sur-recognize`, `sur-dashboard`,
`sur-telegram-bot`, plus the `stream-watchdog.timer`/`duckdns.timer`
timers. Standard `systemctl {start,stop,restart,status}
<name>`/`journalctl -u <name> -f`.

**RPi** (sysvinit): `/etc/init.d/{camera-rtsp,greet-audio-feeder}
{start,stop,restart,status}`. Logs at
`/home/server/sur-floders/logs/{camera-rtsp,greet-audio-feeder}.log`.

### 8.3. Accessing it

- **Dashboard**: `http://<server-LAN-IP>:8080/` (or the Tailscale/public
  address — see §6.3), HTTP Basic Auth with `.env`'s
  `DASHBOARD_USERNAME`/`PASSWORD`. Attendance view at `/attendance`.
- **Live RTSP** (VLC etc.): `rtsp://<server-LAN-IP>:8554/cam02` locally,
  or with `public:<PUBLIC_RTSP_PASSWORD>@` prefixed if connecting from
  outside LAN/Tailscale (force TCP transport for external clients).
- **Telegram**: message the configured bot with `/start` to subscribe to
  alerts, `/stop` to unsubscribe.
- **Recordings**: `/srv/camera_recordings/cam02/`, 5-minute fMP4
  segments, 168h retention, indexed in `segments-index.log` (match a
  `KNOWN`/`UNKNOWN FACE` line in `logs/events.log` to its covering
  recording by timestamp).

### 8.4. Adding a known person

```
mkdir -p known_faces/<Name>
# drop a few clear, well-lit photos of their face in that directory
sudo systemctl restart sur-recognize   # reloads known_faces/ on startup
```

### 8.5. Exporting attendance

```
make export-attendance                  # all records
make export-attendance DATE=2026-09-04  # one day
```

## 9. Troubleshooting

- **`make verify` fails on a service check**: that service isn't
  `active` — check its logs (`journalctl -u <name>` on the server,
  `tail <name>.log` on the RPi) for why.
- **RTSP stream readable but stale/frozen**: `stream_watchdog.py` should
  catch and alert on this within ~9 minutes; check
  `journalctl -u stream-watchdog` for its run history, and
  `logs/watchdog_state.json` for its current consecutive-failure count.
- **No greeting audio in the stream**: confirm
  `greet-audio-feeder`'s Flask endpoint is reachable
  (`curl http://<rpi-ip>:5055/health`) and that `camera_rtsp_server.py`'s
  ffmpeg log doesn't show repeated FIFO-related errors.
- **A restart of `camera_rtsp_server.py` seems to hang / camera busy on
  next start**: check for orphaned `rpicam-vid`/`ffmpeg` processes on
  the RPi (`ps aux | grep -E "rpicam|ffmpeg"`) — see §7.9; the current
  code shouldn't leave these behind, but if it's been bypassed (e.g. a
  manual `kill -9` on the wrapper) they can still be orphaned and need a
  manual `kill`.
- **Dashboard/RTSP not reachable from outside**: confirm router port
  forwards (TCP 8080, TCP 8554) point at the server's *current* LAN IP,
  and that `mediamtx.yml`'s `authInternalUsers` IP ranges match your
  actual LAN subnet if it differs from `192.168.88.0/24`.
