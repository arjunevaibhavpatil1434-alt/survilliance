#!/bin/sh
# Installs and enables the camera-rtsp/recognize/dashboard/fix-clock sysvinit
# services on the target board (no systemd on this Yocto image). Run as root
# on the Pi itself, or via `make services-install` from a machine with SSH
# access set as PI_HOST.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/fix-clock" "$SCRIPT_DIR/camera-rtsp" "$SCRIPT_DIR/sur-recognize" "$SCRIPT_DIR/sur-dashboard" /etc/init.d/
chmod +x /etc/init.d/fix-clock /etc/init.d/camera-rtsp /etc/init.d/sur-recognize /etc/init.d/sur-dashboard

if command -v update-rc.d >/dev/null 2>&1; then
    update-rc.d fix-clock defaults
    update-rc.d camera-rtsp defaults
    update-rc.d sur-recognize defaults
    update-rc.d sur-dashboard defaults
else
    for s in fix-clock camera-rtsp sur-recognize sur-dashboard; do
        for rl in 2 3 4 5; do ln -sf /etc/init.d/$s /etc/rc$rl.d/S20$s; done
    done
fi

echo
echo "Installed. Start with: make services-start"
