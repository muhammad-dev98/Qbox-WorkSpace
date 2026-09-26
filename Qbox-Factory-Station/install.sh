#!/usr/bin/env bash
set -euo pipefail

# Installs the QBox Factory Station agent as a per-user systemd service on
# a factory laptop. Requires: Python 3.10+, BlueZ, D-Bus, systemd (--user
# services) - all standard on a normal desktop Linux install; no Chrome,
# no Web Bluetooth, no manual pairing.

INSTALL_DIR="${QBOX_STATION_INSTALL_DIR:-/opt/qbox-factory-station}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  STATION_USER="${SUDO_USER}"
else
  STATION_USER="$(id -un)"
fi
STATION_HOME="$(getent passwd "${STATION_USER}" | cut -d: -f6)"

echo "Installing QBox Factory Station to ${INSTALL_DIR}..."
sudo mkdir -p "${INSTALL_DIR}"
sudo cp -r "${REPO_DIR}/station_agent" "${INSTALL_DIR}/"
sudo cp "${REPO_DIR}/requirements.txt" "${INSTALL_DIR}/"

sudo python3 -m venv "${INSTALL_DIR}/.venv"
sudo "${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

# Do not force the laptop adapter to LE-only: that disables discovery of
# ordinary BR/EDR devices. QBox uses BLE, while the Station's Bleak client
# handles its GATT connection without changing the host's global mode.
sudo systemctl enable --now bluetooth.service 2>/dev/null || true
sudo rfkill unblock bluetooth 2>/dev/null || true
bluetoothctl power on >/dev/null 2>&1 || true

mkdir -p "${STATION_HOME}/.config/systemd/user"
sed "s#/opt/qbox-factory-station#${INSTALL_DIR}#" "${REPO_DIR}/packaging/qbox-factory-station.service" \
  > "${STATION_HOME}/.config/systemd/user/qbox-factory-station.service"
sudo chown -R "${STATION_USER}:${STATION_USER}" "${STATION_HOME}/.config/systemd"

if [[ -n "${XDG_RUNTIME_DIR:-}" ]] && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable --now qbox-factory-station.service
  echo "Installed as a user service for ${STATION_USER}."
else
  # sudo from a TTY/SSH session often has no user systemd bus. Install a
  # system unit instead so the station still starts and can access BlueZ's
  # system D-Bus; this avoids the misleading 'Failed to connect to bus'
  # failure while preserving the same loopback API.
  # Stop any previous system/user unit before replacing it. Without this,
  # rerunning the installer can leave an older station process listening on
  # 8787 while the new system unit crash-loops with EADDRINUSE.
  sudo systemctl stop qbox-factory-station.service 2>/dev/null || true
  systemctl --user stop qbox-factory-station.service 2>/dev/null || true
  systemctl --user disable qbox-factory-station.service 2>/dev/null || true
  sudo sed "s#^WantedBy=.*#WantedBy=multi-user.target#; s#^Environment=QBOX_STATION_ID=.*#Environment=QBOX_STATION_ID=${STATION_USER}#; s#^\[Service\]#\[Service\]\nUser=${STATION_USER}#" \
    "${STATION_HOME}/.config/systemd/user/qbox-factory-station.service" \
    | sudo tee /etc/systemd/system/qbox-factory-station.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now qbox-factory-station.service
  echo "Installed as a system service for ${STATION_USER} (user systemd bus was unavailable)."
fi

echo "Check status with: sudo systemctl status qbox-factory-station.service"
echo "Station health: curl http://127.0.0.1:8787/station/status"
