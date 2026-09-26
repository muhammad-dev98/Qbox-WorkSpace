# QBox Cross-Repository Audit

Status: implementation audit, 2026-09-01

This audit records observed behavior from the source trees. `Qbox-Backend` and
`Qbox-Hardware` remain independently cloneable repositories; the workspace
`contracts/` directory is documentation only and is not imported at runtime.

## Current Hardware Behavior

- Device identity, local persistence, MQTT transport, health, registration,
  GPIO/camera/locker boundaries, command dispatch, and offline queues live in
  `Qbox-Hardware`.
- Connectivity state is collected locally and can be queued for later MQTT
  publication. Wi-Fi scan, profile connection, and profile deletion are
  currently implemented by the `NetworkManagerAdapter`.
- BLE provisioning requires a short-lived authorization session and stores only
  a token hash in local state. Scan and connect operations are rejected without
  an active session.
- Command results are persisted locally by `command_id`, so redelivery returns
  the prior result instead of executing twice. Command envelopes validate device
  identity, schema version, timestamp, and expiry.
- Systemd packaging enables connectivity and BLE provisioning units, but the
  current units are one-shot status/provisioning entry points, not a full
  long-running BlueZ GATT daemon or connectivity recovery loop.

## Current Backend Behavior

- Device identity, ownership/authorization, lifecycle, certificates,
  provisioning sessions, connectivity state/history, command records, audit,
  MQTT ingestion, and REST APIs live in `Qbox-Backend`.
- Connectivity REST endpoints authorize the caller against the device and
  create BLE provisioning sessions, read state/history, and create remote
  connectivity commands.
- MQTT state and event envelopes are validated before persistence. Secret-like
  fields are rejected and metadata is redacted before storage.
- The backend persists authoritative cloud state; it does not execute Linux
  networking operations.

## Current Contracts

- MQTT namespace: `qbox/v1/devices/{device_uid}/...`.
- Device publishes state, events, telemetry, heartbeat, and acknowledgements;
  device subscribes to commands and configuration.
- Connectivity envelope names are `connectivity.state`, `connectivity.event`,
  and `connectivity.command` with schema version `1`.
- Canonical connectivity REST paths and payloads are documented in
  `contracts/connectivity/v1.md`.

## Current Flows

### Wi-Fi

Online control is app -> authenticated backend -> MQTT -> hardware. Offline
recovery is app -> authenticated BLE session -> hardware -> NetworkManager.
The hardware records state and queues events when MQTT is unavailable.

### BLE

The backend issues a short-lived BLE session token. The device accepts the
session only after local authorization and expiry checks. The repository has a
service boundary and tests for authorization, but a physical BlueZ GATT
transport and encrypted, chunked characteristic protocol are not yet present.

### Registration and lifecycle

Registration is hardware-agent initiated and backend-authorized. The backend
uses explicit registration/lifecycle choices including `UNREGISTERED`,
`REGISTERING`, `REGISTERED`, `SUSPENDED`, and `DECOMMISSIONED` where applicable.

### Health

Hardware health and connectivity data are published independently. Backend
heartbeat ingestion updates device presence; connectivity state distinguishes
Wi-Fi association from MQTT/cloud availability.

## Security Model

- Backend API access is authenticated/authorized through device access checks.
- Device MQTT uses the existing TLS/certificate onboarding boundary.
- Wi-Fi passwords are accepted only by the local provisioning boundary and are
  not placed in backend models, normal MQTT events, logs, or state payloads.
- Command expiry and persisted command results provide stale-command rejection
  and duplicate suppression.

## Findings and Mismatches

1. Hardware production Wi-Fi control now uses `NetworkManagerDbusAdapter` in
   `Qbox-Hardware/platform/qbox_platform/network/networkmanager_dbus.py`; the
   production snapshot collector no longer shells out through command-line network
   tools.
2. BLE provisioning now has a BlueZ GATT application implementation in
   `Qbox-Hardware/platform/qbox_platform/bluetooth/gatt_server.py`.
3. BLE MTU chunking, replay sequence numbers, authenticated AES-GCM encryption,
   failed-attempt lockout, and session expiration are implemented in
   `Qbox-Hardware/platform/qbox_platform/bluetooth/secure_protocol.py` and
   covered by security tests.
4. Connectivity state publication is queue-backed, but a continuously running
   recovery/publisher agent and broker integration test are still required for
   production acceptance.
5. Backend integration tests require PostgreSQL; local execution currently fails
   at test database creation because the database service is unavailable.

## Verification Classification

- UNIT TESTED: hardware connectivity, BLE session boundary, command envelope,
  packaging, rootfs profile audit; hardware suite currently passes.
- BACKEND VERIFIED: Django system checks and migration drift check pass.
- CONTRACT VERIFIED: documented topic/envelope paths and field names are
  aligned by source inspection and focused tests.
- INTEGRATION TESTED: not yet against a live MQTT broker, PostgreSQL, BlueZ, or
  NetworkManager D-Bus.
- PHYSICAL HARDWARE TESTED: no Raspberry Pi, Wi-Fi adapter, BlueZ, or BLE
  validation was available in this environment.
