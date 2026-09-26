# QBox Factory Station — Architecture

## Why this exists

The Factory Panel previously used Chrome's Web Bluetooth API to talk to QBox devices
directly from the browser. On Linux, Web Bluetooth is implemented on top of BlueZ's
D-Bus API — the same `Device1.Connect()` call `bluetoothctl` uses. Live testing
(2026-09-09) proved the real root cause of persistent "Device is offline or
unreachable" failures: this dual-mode Bluetooth adapter advertises default classic
Bluetooth profiles (AVRCP, PnP Information) alongside our custom LE GATT service.
BlueZ's generic `Connect()` tries to negotiate *all* of them, and the classic-profile
negotiation fails and rolls back the whole connection — even though the actual LE
GATT link had already succeeded moments earlier. This affects any client going
through `Device1.Connect()`, Chrome included.

The real fix for that specific failure is device-side (`ControllerMode = le` in
`/etc/bluetooth/main.conf`, forcing the adapter to LE-only so BR/EDR profile
negotiation never happens). The Station Agent exists for the reasons beyond that one
bug: a stable local API surface with real error codes, no browser permission-cache
weirdness, and no dependency on a specific browser to run a factory floor.

## Components

```
React Factory Panel (browser)
        | localhost HTTP + WebSocket (http://127.0.0.1:8787)
        v
QBox Factory Station Agent (station_agent/, Python, this repo)
        | BlueZ D-Bus (via bleak)
        v
QBox Raspberry Pi — existing BLE GATT server (Qbox-Hardware, unchanged)
        | encrypted AES-256-GCM session (existing protocol, unchanged)
        v
QBox Connectivity Agent -> NetworkManager D-Bus -> Wi-Fi
```

**Deliberately reused, not reinvented:** the GATT UUIDs, the chunked wire framing,
and the AES-256-GCM session protocol are Qbox-Hardware's existing, already-hardened
contract (`platform/qbox_platform/bluetooth/{gatt_server,secure_protocol}.py`). The
Station Agent is a native client for that *same* protocol, not a second one. This
was a deliberate design constraint, not an oversight — the crypto layer
(`station_agent/crypto.py`) is tested directly against the real device module
(`tests/test_crypto.py`) to prove wire compatibility, not just similarity.

## station_agent modules

- `crypto.py` — client-side mirror of `BLESecureSession` (HKDF-SHA256 key
  derivation, AES-256-GCM encrypt/decrypt, replay protection). Same
  `cryptography` library the device uses.
- `protocol.py` — chunking/reassembly, identical wire format to the device's
  `BLEChunk`/`BLEReassembler`.
- `ble_client.py` — `bleak`-based BLE client: discovery, connect, identity
  verification, authorize, `wifi.scan`, `wifi.configure`.
- `server.py` — `aiohttp` HTTP + WebSocket API consumed by the Factory Panel.

## HTTP API (implemented)

| Method | Path | Purpose |
|---|---|---|
| GET | `/station/status` | Station health, version, connected devices |
| POST | `/devices/discover` | BLE scan for `QBox-*` advertisements |
| POST | `/devices/{id}/connect` | Connect + verify identity |
| POST | `/devices/{id}/disconnect` | Disconnect |
| POST | `/devices/{id}/authorize` | Establish the encrypted session |
| POST | `/devices/{id}/wifi/scan` | Real Wi-Fi scan via the device |
| POST | `/devices/{id}/wifi/connect` | Provision Wi-Fi credentials |
| GET | `/events` (WebSocket) | `device.connected`/`device.disconnected`/`wifi.*` events |

Error responses are `{"error": {"code": "...", "message": "..."}}` with stable
codes (`BLE_DEVICE_NOT_FOUND`, `BLE_CONNECTION_FAILED`, `BLE_AUTH_FAILED`,
`WIFI_REQUEST_FAILED`, `STATION_UNAVAILABLE`, etc.) — never a raw exception string.

## What is verified live (not just unit-tested)

- Real BLE discovery of a physical QBox (`QBox-738C20`) over `bleak`/BlueZ.
- Real GATT connect + identity read (`QBOX-0D435E439B8E46738C20`), through the
  full HTTP API (`curl -X POST /devices/discover` → `/devices/{id}/connect`),
  against live hardware.
- Crypto interop: `station_agent/crypto.py` encrypt/decrypt round-trips proven
  against the actual `Qbox-Hardware` `BLESecureSession` object in the same
  process (`tests/test_crypto.py`), not just independently re-implemented.

## What is not yet verified live

- `authorize()` end-to-end with a real backend-issued session token (needs the
  device online long enough to receive the MQTT-pushed token hash, then offline
  to test BLE — a timing sequence, not a code gap).
- `wifi.connect` end-to-end (same dependency).
- Multi-station / multi-device concurrency, reconnect-after-crash, and the full
  BLE reliability/stress test suite described in the original request are not
  implemented — this is the core, working path, not the full 25-section spec.

## Installation

See `install.sh` and `packaging/qbox-factory-station.service`. Runs as a
per-user systemd service; no Chrome, no Web Bluetooth, no manual pairing.
