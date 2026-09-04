\
# Surveillance pipeline automation.
#
# Pipeline: CSI camera -> camera_rtsp_server.py (libcamerasrc + GstRtspServer,
# camera-rtsp service) -> recognize_rtsp.py (sur-recognize service) ->
# faces.db -> dashboard/app.py (sur-dashboard service) + notify.py
# (Telegram). Config lives in config.yaml + .env, loaded by config_loader.py.
#
# Runs on a Yocto/sysvinit image (no systemd, no mediamtx, no package
# manager/compiler) - services are plain /etc/init.d scripts in initd/,
# installed via initd/install.sh. This dev machine is separate from the
# target board, so most targets run over SSH; set PI_HOST to override.

PYTHON      ?= python3
PIP         ?= $(PYTHON) -m pip
INITD_DIR   := initd
SERVICES    := camera-rtsp sur-dashboard sur-recognize
PI_HOST     ?= root@192.168.88.157
PI_DIR      ?= /home/server/sur-floders
SSH         := ssh $(PI_HOST)

.PHONY: help install verify run-recognize run-dashboard \
        deploy services-install services-start services-stop services-restart \
        services-status logs-recognize logs-dashboard logs-camera \
        export-attendance clean

help:
	@echo "Local (dev machine) targets:"
	@echo "  install            Install pinned Python dependencies (requirements.txt)"
	@echo "  deploy             Sync this repo to the Pi (PI_HOST=$(PI_HOST))"
	@echo "  clean              Remove __pycache__ directories"
	@echo
	@echo "Remote (run on/against the Pi over SSH) targets:"
	@echo "  verify             Run the full pipeline health check (healthcheck.py)"
	@echo "  services-install   Install + enable the sysvinit services on the Pi"
	@echo "  services-start     Start camera-rtsp, sur-dashboard, sur-recognize (in order)"
	@echo "  services-stop      Stop sur-recognize, sur-dashboard, camera-rtsp (in order)"
	@echo "  services-restart   Stop then start all services"
	@echo "  services-status    Show init.d status for the whole pipeline"
	@echo "  logs-recognize     Tail sur-recognize log"
	@echo "  logs-dashboard     Tail sur-dashboard log"
	@echo "  logs-camera        Tail camera-rtsp log"
	@echo "  export-attendance  Export attendance to CSV (DATE=YYYY-MM-DD optional)"
	@echo
	@echo "Override the target board with: make <target> PI_HOST=root@<ip>"

install:
	$(PIP) install -r requirements.txt

deploy:
	$(SSH) "mkdir -p $(PI_DIR)"
	tar --exclude='.git' --exclude='__pycache__' --exclude='*.mp4' \
	    --exclude='captures' --exclude='unknown_faces' --exclude='attendance_exports' \
	    --exclude='faces.db' --exclude='logs' \
	    -cf - . | $(SSH) "tar -C $(PI_DIR) -xf -"

run-recognize:
	$(PYTHON) recognize_rtsp.py

run-dashboard:
	$(PYTHON) dashboard/app.py

verify:
	$(SSH) "python3 $(PI_DIR)/healthcheck.py"

services-install:
	$(SSH) "cd $(PI_DIR) && $(INITD_DIR)/install.sh"

services-start:
	$(SSH) "/etc/init.d/camera-rtsp start && sleep 2 && /etc/init.d/sur-dashboard start && sleep 1 && /etc/init.d/sur-recognize start"

services-stop:
	$(SSH) "/etc/init.d/sur-recognize stop; /etc/init.d/sur-dashboard stop; /etc/init.d/camera-rtsp stop"

services-restart: services-stop services-start

services-status:
	$(SSH) "for s in $(SERVICES); do /etc/init.d/\$$s status; done"

logs-recognize:
	$(SSH) "tail -f $(PI_DIR)/logs/sur-recognize.log"

logs-dashboard:
	$(SSH) "tail -f $(PI_DIR)/logs/sur-dashboard.log"

logs-camera:
	$(SSH) "tail -f $(PI_DIR)/logs/camera-rtsp.log"

export-attendance:
	$(SSH) "cd $(PI_DIR) && python3 export_attendance.py $(DATE)"

clean:
	find . -name "__pycache__" -type d -not -path "./ai_coding_agent/*" -exec rm -rf {} +
