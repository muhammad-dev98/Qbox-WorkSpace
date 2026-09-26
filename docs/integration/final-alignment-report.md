# QBox Final Alignment Report

Status: aligned contract baseline with explicit release blockers, 2026-09-01

## A-B. Architecture and ownership

`Qbox-Backend` owns users, authorization, device records, lifecycle, policy,
REST, MQTT orchestration, persistence, audit, and app-facing updates.
`Qbox-Hardware` owns Linux, NetworkManager, BlueZ, local state, MQTT client,
registration execution, health, hardware, recovery, and offline behavior.
The only bridge is versioned HTTPS/MQTT/BLE contract documentation.

## C-E. REST and MQTT matrices

Canonical connectivity endpoints are listed in `contracts/connectivity/v1.md`:
provisioning-session creation, state retrieval, event history, and authorized
commands. MQTT uses `qbox/v1/devices/{device_uid}` with `commands`, `state`,
`events`, `command-ack`, `telemetry`, and `heartbeat` suffixes. Payloads use
`schema_version`, `message_id`, `device_uid`, `message_type`, `timestamp`, and
`payload`; command payloads additionally carry command identity and expiry.

## F-G. BLE, lifecycle, and state

BLE application authorization is documented in `contracts/connectivity/v1.md`.
The implementation currently covers short-lived sessions and token hashing;
physical GATT characteristics, MTU-safe chunking, authenticated encryption,
and replay counters remain release work. Backend lifecycle states are explicit
and hardware registration consumes external contracts rather than backend code.
Connectivity state is authoritative from hardware and persisted by backend.

## H-I. Connectivity and error vocabulary

Canonical connectivity values are `UNKNOWN`, `UNPROVISIONED`,
`BLE_PROVISIONING`, `CONNECTING`, `ONLINE`, `OFFLINE`, and `DEGRADED`.
Canonical error examples include `DEVICE_BUSY`, `DEVICE_OFFLINE`,
`WIFI_AUTHENTICATION_FAILED`, `WIFI_DHCP_FAILED`, `WIFI_DNS_FAILED`,
`WIFI_INTERNET_UNAVAILABLE`, `MQTT_UNAVAILABLE`, `BLE_SESSION_EXPIRED`, and
`DEVICE_NOT_AUTHORIZED`. New aliases must not be introduced.

## J-N. Security, state machines, and recovery

Backend authorization precedes remote commands; BLE authorization precedes
local provisioning. Commands expire and are idempotent by `command_id`.
Hardware queues state/events offline and preserves local operation. Candidate
Wi-Fi must be verified before commit and failed candidates must preserve the
known-good profile. Router, internet, MQTT, backend, and power-loss scenarios
are documented test cases; live execution is pending target infrastructure.

## O-Q. Offline behavior and test results

Local state, command history, BLE session state, and event queue are designed
to survive backend/MQTT outages. Hardware unit suite: **38 passed**. Backend
`manage.py check`: **passed**. Backend migration drift check: **passed**.
Backend database tests: **not completed; PostgreSQL was unavailable**.

## R-S. Hardware verification and remaining issues

**Current implementation update:** hardware production Wi-Fi control and network
state collection are D-Bus-first through NetworkManager. BLE provisioning includes
a BlueZ GATT application boundary plus authenticated AES-GCM secure framing,
MTU chunking/reassembly, replay rejection, and temporary failed-attempt lockout.

**Physical execution status:** Raspberry Pi NetworkManager, BlueZ, BLE radio,
MQTT/TLS broker, systemd recovery, GPIO, cameras, and power-loss behavior are
executable through the root gate scripts but cannot pass on this host because
the required hardware/system services are unavailable here.
