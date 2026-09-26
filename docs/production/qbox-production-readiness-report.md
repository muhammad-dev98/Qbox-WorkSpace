# QBox Production Readiness Report

Date: 2026-09-07

Verdict: NOT PRODUCTION READY.

This report is based on source audit, local Factory Panel build, VPS backend verification, local hardware automated tests, and read-only SSH validation of the physical QBox at `192.168.1.4`. Completion is not claimed because the full physical workflow has not been re-executed through the Factory Panel end to end in this session, the physical device requires sudo credentials for deployment, and several required test/status/UI surfaces remain incomplete.

## Architecture

The workspace remains separated by repository boundary:

- `Qbox-Backend`: Django/DRF, device identity, lifecycle, commands, telemetry ingestion, factory operations, inventory, requests, installation, RBAC, audit.
- `Qbox-Hardware`: Raspberry Pi runtime, identity, NetworkManager, GPIO, camera, telemetry, MQTT command execution.
- `Qbox-Factory-Panel`: React/Ant Design/TanStack Query operator console.
- `contracts/`: versioned HTTP/MQTT/device contracts.

Canonical physical device identity remains `hardware_devices.Device`. The legacy `q_box` app still exists for commercial/customer assignment bridging and is still referenced by some backend modules, so it has not been removed.

## Backend

Implemented and verified:

- `factory_ops` models/services/APIs exist for test profiles, test runs, test results, quality gates, burn-in rows, inventory assets, movements, reservations, customer requests, installation orders, installation assignments, installation step results, installation events, and factory audit events.
- `hardware_devices` owns canonical device UID/QBox ID/lifecycle/commands/connectivity/health/telemetry.
- VPS runtime is active: `qbox-development-web`, `qbox-development-websocket`, worker, beat, MQTT consumer/publisher, EMQX, PostgreSQL, Redis, RabbitMQ, MinIO, MediaMTX.
- VPS migrations are applied for `factory_ops`, `hardware_devices`, and `devices_telemetry`.
- VPS DB-aware Django check passed.
- VPS targeted Django suite passed: `173 tests OK`.
- `TestResultStatus` now supports `NOT_STARTED`, `BLOCKED`, `NOT_EXECUTABLE`, `REQUIRES_HUMAN`, and `REQUIRES_EXTERNAL_EQUIPMENT`; migration `factory_ops.0004_extend_test_result_statuses` is applied on VPS.
- Device RUN_TEST ACK ingest now preserves non-binary execution statuses instead of collapsing unsupported or operator/equipment-required outcomes to generic failures.
- Factory requester-account lookup endpoint exists at `/api/v1/factory/requester-accounts/` with factory-view permission checks, search, requester-type filtering, and active-account scoping.

## Hardware

Implemented and verified:

- Physical device reachable: `qbox-dev@192.168.1.4`.
- Hostname: `qbox-885ff5c9`.
- OS/kernel: Debian 12, `6.12.96+rpt-rpi-v8`, `aarch64`.
- CPU/RAM/storage observed: Cortex-A72, 4 CPUs, 1.8 GiB RAM, root filesystem 77% used.
- Network observed: `wlan0` on `192.168.1.4/24`, Tailscale `100.116.39.50`, gateway ping PASS, DNS resolves `backend.qbox.sa`.
- Services observed active: `qbox-registration-agent`, `qbox-streaming-agent`, `mediamtx`, `qbox-gpio-safe-init`, `qbox-platform-init`, `NetworkManager`, SSH.
- Cameras observed: USB camera `Sonix ... UC21A SN0020`; CSI stream process active via `rpicam-vid`.
- GPIO observed: configured lines 12/16/20/21 held by `gpioset`, feedback line 17 readable metadata present.
- Hardware automated tests passed locally: `148 passed, 1 warning`.

New fix implemented:

- `QBoxSettings.from_env()` now tolerates unreadable config/secret paths instead of crashing unprivileged CLI diagnostics.
- Regression test added for unreadable bootstrap secret path.
- RUN_TEST unsupported steps now report `NOT_EXECUTABLE` with `NOT_EXECUTED` evidence and `RUN_TEST_UNSUPPORTED` error code.
- Non-disruptive RUN_TEST executors added for `WIFI`, `MQTT`, `TELEMETRY`, and `HEARTBEAT`; these use existing network/telemetry/heartbeat code paths and explicitly report whether publish/round-trip validation was executed.

Deployed and verified on the physical device (2026-09-07, this session):

- Operator provided sudo access for `qbox-dev@192.168.1.4`. Ran `QBOX_DEV_SUDO_PASSWORD=... ./scripts/deploy-dev.sh 192.168.1.4` (non-interactive path documented in the script itself; password never placed on the command line or in a file). Deploy synced code, ran `install.sh`, restarted `qbox-registration-agent`, `qbox-streaming-agent`, and `mediamtx`, and confirmed `qbox-registration-agent.service` reached `active`.
- `qbox status` no longer crashes and now returns full structured status (previously fixed `QBoxSettings.from_env()` tolerance for unreadable secret paths, confirmed live).
- New finding during this deploy: `qbox status` reported `Certificate: {'status': 'INVALID', 'error': 'installed certificate identity mismatch'}` even though the device was actively `REGISTERED`/`OPERATIONAL` and MQTT-connected. Root cause: the device's certificate CN is provisioned as the hardware `certificate_identity` fingerprint (see `IdentityManager.ensure_identity` / `CSRManager.ensure_csr`), not the `device_uid`. `RegistrationApplication` already validates against the correct `certificate_identity`, but `runtime/status.py::build_runtime_status` and the registration-agent CLI's `certificate` command only ever checked against `expected_device_uid`, so they raised a false mismatch on every call. Fixed both call sites to read `identity_fingerprint` from the persisted device identity JSON and pass it as `expected_certificate_identity`. Added regression tests (`tests/test_identity_certificate.py`) exercising `CertificateManager.validate_installed_certificate` directly against a certificate CN'd with a fingerprint distinct from `device_uid`. Full local suite: `150 passed` (up from 148). Redeployed; physical device now reports `Certificate: {'state': {'fingerprint_sha256': ..., 'not_after': '2027-09-04T14:21:43+00:00'}}` with no error.
- Also removed a dead `--test` option in `scripts/deploy-dev.sh` that referenced a nonexistent `scripts/qbox-test.sh` (surfaced when first exercising deploy with `--test` this session); no such remote acceptance-test script exists in this repo, so the option was removed rather than left broken.
- Confirmed via journal that `telemetry_agent` continued emitting `telemetry_cycle_completed` on a live ~30s cadence immediately after the restart (23:53:10, 23:53:40, 23:54:11, 23:54:41 UTC), i.e. the registration-agent restart did not disrupt the telemetry loop.

## Factory Panel

Implemented and verified:

- React/Ant Design/TanStack Query app builds successfully.
- Existing real API-backed pages cover dashboard, devices, Device 360, test runs, test profiles, QA, batches, stations, inventory, reservations, customer requests, alerts, audit, installations, and technicians.
- Application shell navigation was expanded to expose the requested operations map with route aliases pointing to existing canonical API-backed pages.
- List pages now initialize filters from URL query params for operational slices such as failed tests, available inventory, and active installations.
- Factory Panel visual system was modernized with a shared industrial-console CSS layer: polished sidebar/topbar, responsive content shell, global search styling, compact table chrome, consistent page headers, filter bars, metric cards, section cards, modal/form surfaces, and login screen.
- Frontend verification after the redesign: `npm run lint` PASS and `npm run build` PASS.

Limitations:

- Several requested submodules are route aliases to canonical pages, not dedicated full-feature workstations.
- Browser-driven Factory Panel E2E was not completed because the browser runtime was unavailable and Playwright is not installed locally.
- Bundle warning remains: single client chunk is larger than 500 kB.

## Telemetry

Implemented:

- Backend telemetry models/views and hardware telemetry agents exist.
- Physical device journal shows repeated `telemetry_cycle_completed`.
- Factory Panel Device telemetry panel uses real backend telemetry endpoints.

Not fully commissioned:

- Live browser WebSocket telemetry was not manually verified in the panel in this session.

## WebSocket

Implemented:

- Canonical routes exist, including per-device hardware route and factory dashboard route.
- Factory Panel uses realtime invalidation through TanStack Query.
- VPS `qbox-development-websocket` container is running.

Not fully commissioned:

- No browser-level WebSocket event replay/test was completed in this session.

## MQTT

Implemented:

- Canonical MQTT namespace is `qbox/v1/devices/{device_uid}/...`.
- Backend MQTT consumer/publisher containers are healthy on VPS.
- Physical device registration agent and streaming/telemetry loops are running.

Not fully commissioned:

- A fresh physical `Factory Panel -> Backend -> MQTT -> QBox -> MQTT -> Backend -> WebSocket -> Factory Panel` command was not executed in this session.

## Testing

Implemented:

- Backend factory/device/telemetry targeted tests: `170 OK` on VPS.
- Hardware tests: `148 passed` locally.
- Factory Panel build: passed.

Not completed:

- Full backend repository regression.
- Factory Panel browser E2E.
- Live negative/concurrency/security campaigns through the actual UI.

## QA

Implemented:

- Quality gate model, requirements, approvals, and lifecycle-gated transition service exist.
- QA approval/rejection records are auditable.

Limitations:

- Physical inspection and final QA are not yet complete dedicated physical workflows in the panel.

## Inventory

Implemented:

- Serialized `InventoryAsset`, append-only `InventoryMovement`, `InventoryReservation`.
- Transactional reservation service with row locking and active-reservation uniqueness.

Mismatch:

- Requested status vocabulary includes `FACTORY`, `WAREHOUSE`, `AVAILABLE`, `WITH_TECHNICIAN`, `QUARANTINE`, `REPAIR`; current implementation uses `READY_FOR_INSTALLATION`, `MAINTENANCE`, etc.

## Customer Requests

Implemented:

- `QBoxRequest` API and service exist.
- Approval reserves qualified inventory and creates/dispatches installation flow.
- Factory requester-account lookup API is deployed on the VPS and covered by permission/search/filter tests.
- Factory Panel request modal now uses remote account search/select instead of requiring operators to paste raw `accounts.Account` UUIDs.

Limitations:

- Browser-driven creation of a real customer request through the running Factory Panel was not completed in this pass.

## Installation

Implemented:

- Installation order, assignment, required ordered step enforcement, retry, QA approval/rejection, activation flow.
- Required steps match the canonical list: `DEVICE_SCANNED`, `SITE_VERIFIED`, `PHYSICAL_INSTALLATION`, `POWER_VERIFIED`, `NETWORK_VERIFIED`, `CAMERA_VERIFIED`, `LOCKER_VERIFIED`, `MQTT_VERIFIED`, `TELEMETRY_VERIFIED`.

Limitations:

- Installation physical checks can record evidence, but dedicated backend-triggered validation commands for every step are not fully implemented.

## Technician

Implemented:

- Technician list is derived from `accounts.CustomUser` permissions/roles rather than a duplicate technician model.
- Assignment/workload views exist in the panel.

Limitations:

- Performance reporting is currently an alias to the technician list, not a full analytics module.

## Assignment

Implemented:

- Customer assignment is reconciled through existing `q_box` management service after successful installation completion.

Risk:

- `QBoxRequest` to `InstallationOrder` is linked by shared `correlation_id`, not a structural FK.

## Activation

Implemented:

- Installation completion transitions device to `INSTALLED` then `ACTIVE`.
- Inventory transitions to installed/active.

Limitations:

- Activation currently relies on installation step evidence and lifecycle/service checks; a dedicated activation preflight endpoint is not yet present.

## Security

Implemented:

- Backend tests cover auth, object/device command rejection, throttling, invalid bootstrap secrets, revoked identities, and in-flight command conflict handling.
- Factory Panel uses permission guards.

Limitations:

- Full RBAC campaign through the live UI was not completed.

## Audit

Implemented:

- Device lifecycle audit and factory audit events exist.
- Inventory movement ledger exists.
- Installation events exist.

Limitations:

- Not every requested event was manually proven in this session through UI/API/DB after each stage.

## Automated Tests

| Area | Result |
|---|---|
| Backend targeted factory/device/telemetry | PASS, 173 tests on VPS |
| Hardware full suite | PASS, 148 tests locally |
| Factory Panel build | PASS |
| Factory Panel lint | PASS |
| Backend full repo regression | NOT_RUN |
| Factory Panel E2E | NOT_RUN |

## Physical Device Tests

| Area | Evidence | Status |
|---|---|---|
| SSH access | `qbox-dev@192.168.1.4` | PASS |
| Identity | Runtime processes use `QBOX-0D435E439B8E46738C20`; static `/etc/qbox/device.json` still blank | WARN |
| OS/kernel | Debian 12, `6.12.96+rpt-rpi-v8` | PASS |
| CPU/RAM/storage | Observed via SSH | PASS |
| Wi-Fi/network | `wlan0` connected, gateway ping PASS | PASS |
| Cameras | CSI and USB streaming processes/devices observed | PASS/WARN |
| GPIO | GPIO metadata and held output lines observed | PASS |
| Services | QBox agents active | PASS |
| MQTT | Agents running; full fresh command roundtrip not rerun | PARTIAL |
| Telemetry | Agent logs show cycles; backend/UI live receipt not rerun | PARTIAL |
| CLI diagnostics | `qbox status` crashes before local fix deployment | FAIL_FIXED_NOT_DEPLOYED |

## Full E2E Test

Not completed in this session. Prior docs claim earlier physical campaigns, but this report does not reuse those claims as current completion evidence. The full required chain still needs a fresh run:

`Factory Panel -> Backend API -> DB/services -> MQTT -> physical QBox -> result -> MQTT -> Backend -> WebSocket -> Factory Panel`.

## Acceptance Matrix

| Area | Implemented | Automated Test | Physical Test | UI Test | Status |
|---|---:|---:|---:|---:|---|
| Registration | Yes | Yes | Partial | Not rerun | Partial |
| Provisioning | Yes | Yes | Partial | Not rerun | Partial |
| Hardware Discovery | Yes | Yes | Prior/read-only partial | Not rerun | Partial |
| GPIO | Yes | Yes | Read-only observed | Not rerun | Partial |
| Cameras | Yes | Yes | Read-only observed | Not rerun | Partial |
| QR | Partial | Yes crypto tests | Not rerun | Not rerun | Incomplete |
| Wi-Fi | Yes | Yes | Non-disruptive PASS | Not rerun | Partial |
| MQTT | Yes | Yes | Not fresh command | Not rerun | Partial |
| Telemetry | Yes | Yes | Agent cycles observed | Build only | Partial |
| WebSocket | Yes | Yes backend | Not applicable | Not rerun | Partial |
| Testing | Yes | Yes | Partial | Build only | Partial |
| QA | Yes | Yes | Not rerun | Not rerun | Partial |
| Burn-In | Model only | Partial | Not rerun | Alias only | Incomplete |
| Inventory | Yes | Yes | Not applicable | Build only | Partial |
| Customer Request | Yes | Yes | Not applicable | Build only | Partial |
| Reservation | Yes | Yes | Not applicable | Build only | Partial |
| Dispatch | Yes | Yes | Not rerun | Build only | Partial |
| Installation | Yes | Yes | Not rerun | Build only | Partial |
| Technician | Partial | Yes | Not applicable | Build only | Partial |
| Installation QA | Yes | Yes | Not rerun | Build only | Partial |
| Assignment | Yes via `q_box` service | Yes | Not rerun | Not rerun | Partial |
| Activation | Yes | Yes | Not rerun | Not rerun | Partial |
| Audit | Yes | Yes | Not rerun | Build only | Partial |
| RBAC | Yes | Yes | Not applicable | Not rerun | Partial |

## Remaining Blockers

| Issue | Component | Severity | Why It Exists | Project-Owned | Required Action |
|---|---|---:|---|---:|---|
| ~~Hardware CLI fix not deployed~~ | Qbox-Hardware / physical QBox | — | RESOLVED 2026-09-07: deployed via `scripts/deploy-dev.sh 192.168.1.4` with operator-provided sudo; `qbox status` verified working live | — | none |
| ~~Certificate falsely reported INVALID~~ | Qbox-Hardware | — | RESOLVED 2026-09-07: `status.py`/CLI `certificate` command now pass `expected_certificate_identity`; verified live on physical device | — | none |
| Full physical E2E not rerun | Whole system | Critical | Needs live UI/API/MQTT/device execution window | Yes | Run complete workflow from panel and verify DB/realtime after each stage |
| Observed telemetry cadence is ~30s, not ~6s | Qbox-Hardware | Medium | Journal on physical device shows `telemetry_cycle_completed` roughly every 30 seconds, not the ~6s assumed by prior planning docs | Yes | Confirm actual intended interval with the telemetry agent config/spec before building UI/backend assumptions around a 6s cadence |
| Missing dedicated physical test executors | Hardware/backend profiles | High | `QR`, `RECONNECT`, `INTEGRATED_SYSTEM`, `POWER_RECOVERY`, `BURN_IN`, `PHYSICAL_INSPECTION`, and `FINAL_QA` remain unsupported as RUN_TEST executors | Yes | Implement the remaining executors safely and prove them on physical hardware |
| Factory Panel submodules are aliases | Factory Panel | High | Existing APIs support canonical pages, not every requested module as a full workstation | Yes | Build dedicated pages for telemetry, reports, burn-in, admin users/roles, quality inspection |
| Static `/etc/qbox/device.json` has blank UID | Hardware image/runtime | Medium | Runtime identity lives under `/etc/qbox/identity/device.json`; static template remains blank | Yes | Confirm all tools read identity path; optionally improve status diagnostics to display canonical identity source |
| Structural request-installation link missing | Backend | Medium | Uses shared `correlation_id` instead of FK | Yes | Add FK from installation/request or fulfillment record with migration |
| UI E2E not run | Factory Panel | Medium | Browser automation not executed in this pass | Yes | Run login/workflow/browser checks against `https://backend.qbox.sa` |
| Local bundle too large | Factory Panel | Low | Routes are bundled in one chunk | Yes | Add route-level code splitting |
