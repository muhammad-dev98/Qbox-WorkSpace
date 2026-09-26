#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/bluetooth/main.conf ]]; then
  # Always normalize the active configuration. A previous installer version
  # may have left ControllerMode=le in either the main file or a duplicate
  # [General] section; restoring an old backup could reintroduce the bug.
  sudo sed -i -E 's/^\s*ControllerMode\s*=.*$/ControllerMode=dual/' /etc/bluetooth/main.conf
  if ! grep -q '^ControllerMode=dual$' /etc/bluetooth/main.conf; then
    printf '\n[General]\nControllerMode=dual\n' | sudo tee -a /etc/bluetooth/main.conf >/dev/null
  fi
fi
sudo systemctl enable --now bluetooth.service
sudo rfkill unblock bluetooth || true
bluetoothctl power on || true
bluetoothctl show || true
echo "Scanning for 15 seconds..."
bluetoothctl --timeout 15 scan on >/dev/null 2>&1 || true
echo "Discovered devices:"
bluetoothctl devices || true
echo "Bluetooth repaired. For a live scan use: bluetoothctl (then type 'scan on' and wait)."
