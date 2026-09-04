\
# Surveillance pipeline automation.
#
# Split architecture - see README.md "What runs where":
#   RPi4 (sysvinit, no systemd): camera_rtsp_server.py (camera-rtsp),
#     greet_audio_feeder.py (greet-audio-feeder) - input only.
#   This server (systemd): mediamtx, recognize_rtsp.py (sur-recognize),
#     dashboard/app.py (sur-dashboard), telegram_bot.py (sur-telegram-bot),
#     stream_watchdog.py (stream-watchdog.timer), DuckDNS updater
#     (duckdns.timer).
#
# Run these targets from this repo checkout on the server - that's where
# systemctl and the RPi's SSH key both live. `make start`/`make stop`
# drive both machines in the right dependency order in one command.

PYTHON       ?= python3
PIP          ?= $(PYTHON) -m pip
INITD_DIR    := initd
PI_HOST      ?= root@192.168.88.157
PI_DIR       ?= /home/server/sur-floders
SSH          := ssh $(PI_HOST)

SERVER_SERVICES := mediamtx sur-recognize sur-dashboard sur-telegram-bot
RPI_SERVICES     := camera-rtsp greet-audio-feeder

.PHONY: help install deploy-rpi verify \
        start stop restart status \
        start-rpi stop-rpi start-server stop-server \
        logs-recognize logs-dashboard logs-telegram-bot logs-mediamtx \
        logs-camera logs-greet-feeder logs-watchdog \
        export-attendance clean

help:
	@echo "Single-command control (runs against both the server and the RPi):"
	@echo "  start              Start everything: RPi input side, then mediamtx,"
	@echo "                     then sur-recognize/sur-dashboard/sur-telegram-bot"
	@echo "  stop               Stop everything, reverse order"
	@echo "  restart            stop then start"
	@echo "  status             Show status of every service on both machines"
	@echo "  verify             Run the full pipeline health check (healthcheck.py)"
	@echo
	@echo "Setup:"
	@echo "  install            Install pinned Python dependencies (requirements.txt"
	@echo "                     + dashboard/requirements.txt)"
	@echo "  deploy-rpi         Sync camera_rtsp_server.py, greet_audio_feeder.py"
	@echo "                     and their initd/ scripts to the RPi (PI_HOST=$(PI_HOST))"
	@echo
	@echo "Logs:"
	@echo "  logs-recognize     journalctl -f sur-recognize (server)"
	@echo "  logs-dashboard     journalctl -f sur-dashboard (server)"
	@echo "  logs-telegram-bot  journalctl -f sur-telegram-bot (server)"
	@echo "  logs-mediamtx      journalctl -f mediamtx (server)"
	@echo "  logs-watchdog      journalctl -f stream-watchdog (server)"
	@echo "  logs-camera        RPi camera-rtsp log, over SSH"
	@echo "  logs-greet-feeder  RPi greet-audio-feeder log, over SSH"
	@echo
	@echo "  export-attendance  Export attendance to CSV (DATE=YYYY-MM-DD optional)"
	@echo "  clean              Remove __pycache__ directories"
	@echo
	@echo "Override the RPi with: make <target> PI_HOST=root@<ip>"
	@echo "Most server-side targets need sudo - run this Makefile as a user with it."

install:
	$(PIP) install -r requirements.txt
	$(PIP) install -r dashboard/requirements.txt

deploy-rpi:
	scp camera_rtsp_server.py greet_audio_feeder.py $(PI_HOST):$(PI_DIR)/
	scp $(INITD_DIR)/camera-rtsp $(INITD_DIR)/greet-audio-feeder $(PI_HOST):/etc/init.d/
	$(SSH) "chmod +x /etc/init.d/camera-rtsp /etc/init.d/greet-audio-feeder"

verify:
	$(PYTHON) healthcheck.py

# --- RPi (input side) ---

start-rpi:
	$(SSH) "/etc/init.d/greet-audio-feeder start && sleep 1 && /etc/init.d/camera-rtsp start"

stop-rpi:
	$(SSH) "/etc/init.d/camera-rtsp stop; /etc/init.d/greet-audio-feeder stop"

# --- Server (mediamtx, recognition, dashboard, telegram) ---
#
# sur-recognize is BindsTo=mediamtx.service, so it comes up/down with it -
# still started explicitly below for a clear ordering in the log/output.

start-server:
	sudo systemctl start mediamtx
	sleep 3
	sudo systemctl start sur-recognize sur-dashboard sur-telegram-bot

stop-server:
	sudo systemctl stop sur-telegram-bot sur-dashboard sur-recognize mediamtx

# --- Combined, single-command entry points ---

start: start-rpi start-server
	@echo "Started. Check with: make status"

stop: stop-server stop-rpi
	@echo "Stopped."

restart: stop start

status:
	@echo "--- RPi ---"
	@$(SSH) "for s in $(RPI_SERVICES); do /etc/init.d/\$$s status; done"
	@echo "--- Server ---"
	@for s in $(SERVER_SERVICES); do echo -n "$$s: "; systemctl is-active $$s; done
	@echo -n "stream-watchdog.timer: "; systemctl is-active stream-watchdog.timer
	@echo -n "duckdns.timer: "; systemctl is-active duckdns.timer

# --- Logs ---

logs-recognize:
	journalctl -u sur-recognize -f

logs-dashboard:
	journalctl -u sur-dashboard -f

logs-telegram-bot:
	journalctl -u sur-telegram-bot -f

logs-mediamtx:
	journalctl -u mediamtx -f

logs-watchdog:
	journalctl -u stream-watchdog -f

logs-camera:
	$(SSH) "tail -f $(PI_DIR)/logs/camera-rtsp.log"

logs-greet-feeder:
	$(SSH) "tail -f $(PI_DIR)/logs/greet-audio-feeder.log"

export-attendance:
	$(PYTHON) export_attendance.py $(DATE)

clean:
	find . -name "__pycache__" -type d -not -path "./ai_coding_agent/*" -exec rm -rf {} +
