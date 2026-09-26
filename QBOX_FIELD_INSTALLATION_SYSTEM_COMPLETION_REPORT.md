# QBox Field Installation System Completion Report

Date: 2026-09-19  
Scope: Qbox-Backend, Qbox-Hardware, Qbox-Technican-App, Qbox-Homeowner-App  
Excluded by design: Qbox-Merchant-App and Qbox-Factory-Panel (no compatibility change was required)

## 1. Executive result

The software path for backend-controlled field commissioning is implemented and regression-tested. The backend now publishes an immutable `QBOX_INSTALLATION_TEST_V4` profile with the requested exact 20-step order. The Technician App renders the profile attached to the backend TestRun, performs BLE-native onboarding before MQTT, and cannot manufacture PASS results for device-verified steps. The Homeowner App consumes the same lifecycle and now understands the V4 step vocabulary.

Qbox-Hardware now automatically advertises its BLE commissioning service whenever Wi-Fi is not genuinely usable. Advertising stops only after Wi-Fi association, DHCP, DNS, and Internet checks all pass. A mere access-point association is not treated as online. An MQTT broker outage does not reopen Wi-Fi commissioning because MQTT is a separate commissioning layer after Internet connectivity.

The development image alone now has these intentional lab defaults:

- hostname: `qbox-dev`
- local `qbox-dev` password: `qazi1234`
- Wi-Fi SSID: `Ata-Qazi`
- Wi-Fi password: `foratta1234`

Factory and production image profiles do not receive these values. Rootfs auditing rejects leakage of the development hostname or Wi-Fi profile into non-development images.

The code and automated suites pass for the changed installation path. A physical Raspberry Pi/QBox was not connected to this execution environment, so real camera, GPIO, solenoid, feedback, radio, image-flash, and end-to-end technician results remain explicitly BLOCKED. The physical fixture was not reset because its exact installation ID could not be safely identified and the local development database rejected the configured credentials. No claim is made that the physical device is clean or installation-ready.

## 2. Architecture before and after

### Before

- The backend already contained the canonical InstallationOrder, TestProfile/TestRun/TestResult, evidence, corrective-action, handover, QA, and atomic activation/binding architecture.
- Field profile V3 used a different set/order of steps than the requested technician profile.
- Several code paths assumed a global client-side required-step list rather than always honoring the immutable profile attached to an existing run.
- HANDOVER could be represented separately from the authoritative final TestRun step.
- Automatic BLE shutdown treated Wi-Fi association alone as online, even if DHCP, DNS, or Internet access failed.
- Development image credentials were expected as build-time inputs and the required fixed lab defaults were not consistently propagated and audited.

### After

```text
Homeowner request
      |
      v
Backend InstallationOrder + immutable TestProfileVersion V4
      |
      +--> Technician App executes backend-provided workflow
      |       BLE identity/onboarding -> network -> MQTT -> device tests
      |
      +<-- TestResult/device ACK/BLE evidence, append-only attempts
      |
      +--> Handover -> submission -> QA/corrective action/retest
      |
      v
Atomic activation + customer/address binding
      |
      v
Homeowner lifecycle projection
```

The repositories remain independent. They coordinate only through existing API, MQTT, BLE, and schema contracts; no cross-repository source imports were introduced.

## 3. Exact technician commissioning profile

`QBOX_INSTALLATION_TEST_V4` is migration-seeded as a new immutable profile version. V1-V3 remain available for historical TestRuns.

| # | Installation step | Execution/verification |
|---:|---|---|
| 01 | DEVICE IDENTITY | Backend verifies the scanned encrypted device identity against the allocated device |
| 02 | BLE DISCOVERY | Technician phone performs BLE connect |
| 03 | BLE AUTHORIZATION | Technician phone performs BLE authorization |
| 04 | WIFI SCAN | Technician phone requests a real scan over BLE |
| 05 | WIFI PROVISION | Technician phone sends credentials over authorized BLE |
| 06 | WIFI CONNECTED | Device-verified `WIFI_CONNECT` result |
| 07 | NETWORK / INTERNET | Device-verified `WIFI_INTERNET` result |
| 08 | MQTT | Device-verified MQTT result |
| 09 | TELEMETRY | Device-verified telemetry result |
| 10 | INTERNAL CAMERA | Device-verified internal-camera result |
| 11 | EXTERNAL CAMERA | Device-verified external-camera result |
| 12 | RED LED | Device-verified red-LED result |
| 13 | GREEN LED | Device-verified green-LED result |
| 14 | BUZZER | Device-verified buzzer result |
| 15 | SOLENOID | Device-verified solenoid actuation result |
| 16 | SOLENOID FEEDBACK | Device-verified feedback result |
| 17 | LOCKER OPEN/CLOSE | Device-verified solenoid-cycle result |
| 18 | INTEGRATED SYSTEM TEST | Device-verified integrated-system result |
| 19 | FINAL INSTALLATION INSPECTION | Actor-stamped technician attestation |
| 20 | HANDOVER | Handover service validates checklist and customer acknowledgement, then grades the final step |

Generic step completion cannot grade HANDOVER. It must pass through the handover domain service with a non-empty, all-true checklist and customer acknowledgement.

## 4. Backend changes

- Added the V4 step vocabulary while retaining all historical choices.
- Added migration `0036_seed_qbox_installation_test_v4.py` to seed/publish V4 and retire the previously published version without editing old versions.
- The required sequence now matches the 20 requested steps exactly.
- `InstallationService.required_steps(order)` reads the ordered `installation_step_type` tags from the TestRun's immutable profile version. Existing V1-V3 installations therefore continue under their original profile.
- Ordering, dispatch, current-step serialization, completion gates, retries, and finalization all use the run-specific sequence.
- Device identity remains backend-verified. A caller-supplied PASS does not bypass encrypted QR/device matching.
- BLE steps continue through TestRun/TestResult via begin and ingest operations.
- Device-verified steps continue through real MQTT RUN_TEST dispatch and ACK ingestion; the technician cannot self-report PASS.
- HANDOVER is now the authoritative final V4 TestRun step and can only be resolved by the handover workflow.
- Test attempts remain append-only. Retest creates a new TestResult/InstallationStepResult attempt rather than overwriting history.
- PDF-only `reportlab` imports were moved out of the device-token verification import path, so QR verification does not depend on optional PDF rendering at runtime.

### API impact

Existing endpoints are retained. Installation detail now exposes the run-specific V4 sequence for new runs and historical sequences for older runs. New values in `step_type` are additive:

`DEVICE_IDENTITY`, `WIFI_CONNECTED`, `NETWORK_INTERNET_VERIFIED`, `CAMERA_EXTERNAL_VERIFIED`, `SOLENOID_FEEDBACK_VERIFIED`, `FINAL_INSTALLATION_INSPECTION`, and `HANDOVER`.

### Database impact

- New Django migration: `factory_ops.0036_seed_qbox_installation_test_v4`.
- No historical TestRun/TestResult rows are rewritten.
- V4 is published; older published field versions become retired but remain queryable.

## 5. Hardware changes

### BLE offline/recovery behavior

The connectivity watchdog now defines usable network connectivity as all of:

1. Wi-Fi associated.
2. DHCP address available.
3. DNS check passed.
4. Internet probe passed.

When any check is false, automatic BLE commissioning remains or becomes available. When all four pass, an automatically started BLE session is stopped. Explicit operator/diagnostic BLE sessions are not silently stopped by the watchdog. NetworkManager Wi-Fi autoconnect suppression/restoration remains tied to BLE commissioning to reduce Raspberry Pi shared-radio contention.

MQTT is intentionally not part of this BLE stop boundary: an Internet-connected device with a broker outage needs MQTT recovery, not Wi-Fi credential reprovisioning.

### Development image

- `image/profiles/development.yaml` owns the fixed development hostname, password hash, and Wi-Fi defaults.
- Build-time password and Wi-Fi environment variables still override these defaults.
- The image-generation config passes fixed hostname and development Wi-Fi into the QBox install hook.
- The hook writes a mode-0600 NetworkManager connection and the development hostname.
- `qbox-hostname-init.service` reads the generated QBox environment so the fixed hostname survives boot.
- Live development installs preserve the same fixed hostname behavior.
- Rootfs audit validates exact development defaults and rejects their presence outside the development profile.
- Shell and Python static checks cover the changed build/install scripts.

The repository's full hardware suite also reconciles the registered `FINAL_QA` executor and the established evidence semantics: real-device identity/system inspection reports physical-device evidence; mock controllers remain unit evidence.

## 6. Technician App changes

- Added the exact V4 20-step contract and labels while preserving explicit legacy step types.
- The job screen renders `execution_workflow.steps` supplied by the backend instead of creating a second client-side state machine.
- QR scanning submits `DEVICE_IDENTITY` for V4 while legacy orders remain display-compatible.
- BLE connect/authorize/scan/provision use the BLE workflow.
- DEVICE_VERIFIED rows expose hardware execution, never a generic "Mark passed" action.
- HANDOVER has no generic PASS control. The handover UI requires all checklist items and customer acknowledgement.
- Submission appears only after every backend workflow step is complete and the handover record exists.
- Hardware-test routing recognizes both V4 external-camera and legacy camera step values.
- Added an automated assertion for the exact 20-step order.
- Implementation was checked against the repository-required official [Expo SDK 57 reference](https://docs.expo.dev/versions/v57.0.0/).

## 7. Homeowner App integration

- The shared API contract includes every V4 step plus V1-V3 legacy values.
- Homeowner-safe text maps the new technical values to understandable progress descriptions.
- The app remains a projection of backend status; it does not control technical PASS/FAIL, activation, owner binding, or address binding.
- Existing lifecycle, notification, completion-report, and active-device gates continue to use backend data.

## 8. Technical workflows

### Wi-Fi/BLE onboarding

Offline QBox -> BLE advertisement -> phone discovery -> authorization -> real Wi-Fi scan -> credential provision -> QBox reconnect -> device Wi-Fi and Internet tests. Wi-Fi credentials are not included in backend TestResult evidence.

### MQTT and telemetry

MQTT and telemetry occur only after Wi-Fi and Internet verification. The backend dispatches the existing device RUN_TEST command and waits for the device ACK/ingested TestResult.

### Cameras and hardware

Internal camera, external camera, LEDs, buzzer, solenoid, feedback, locker cycle, and integrated-system checks reuse existing device executors. The app cannot manufacture device results. Camera live-stream support remains separate from capture/test evidence.

### Evidence, correction, and rerun

Evidence retains uploader, category, optional step, checksum, type, size, and time. QA may open corrective actions. Rework reopens the controlled workflow and permits the affected step to be retested. Each run creates a new attempt and preserves prior failures/passes.

### Handover, QA, and activation

Handover requires technician identity, an all-true checklist, and customer acknowledgement. Submission and QA remain separate. Final completion performs backend-controlled device activation and customer/address binding; technicians cannot directly bind ownership.

### Realtime, offline, and recovery

Existing installation and test events remain the realtime source. The Technician App derives visible workflow state from refreshed backend data and retains its existing network/offline support. BLE provides the recovery channel before Wi-Fi is usable.

## 9. Security and RBAC

- Critical state transitions remain server-side and actor-stamped.
- Device identity is cryptographically verified when an issued QR token is supplied.
- BLE authorization precedes credential provisioning.
- Device-verified outcomes require device-side execution evidence.
- Wi-Fi passwords are not included in commissioning result evidence.
- Development credentials are an explicit lab-only exception and are documented as unsafe for production.
- SSH remains public-key-only; the fixed password is for the development local-console account unless explicitly overridden.
- Production/factory rootfs validation prevents development defaults from crossing the profile boundary.

## 10. Automated validation

| Repository/check | Result |
|---|---|
| Backend Django system check | PASS |
| Backend migration drift check | PASS (`No changes detected`) |
| Backend commissioning/service/API/concurrency suite | PASS: final run includes 48 tests |
| Hardware targeted connectivity/image tests | PASS: 34 tests |
| Hardware full suite | PASS: 236 passed, 1 skipped |
| Hardware changed shell scripts `bash -n` | PASS |
| Hardware changed Python modules compile | PASS |
| Technician Jest | PASS: 44 tests |
| Technician TypeScript | PASS |
| Technician Expo lint | PASS |
| Homeowner Jest | PASS: 86 tests |
| Homeowner TypeScript | BLOCKED by unrelated pre-existing form/component errors; no remaining error was reported for the V4 installation mapping |

The hardware suite emitted one existing paho-mqtt callback API deprecation warning.

An actual `.img` was not produced in this environment: the available host is Ubuntu 24.04 amd64, while the deterministic image pipeline requires its supported Debian arm64 build host unless experimental cross-build mode is explicitly chosen. The fake-tool/config integration, rootfs profile audit, shell syntax, and image-builder regression tests passed; this is not represented as a real image-flash result.

## 11. Teardown and physical device state

The isolated Django test database was created and destroyed by the test runner. No persistent automated installation fixture remains in that database.

Physical teardown was not executed. The safe teardown command requires the exact `device_uid` and `installation_id`. A read-only attempt to inspect the local development database failed because PostgreSQL rejected the configured `qbox_local` credentials. There was also no authenticated physical-device session in this environment. Guessing a target would risk deleting a real installation, so no destructive command was run.

After restoring local DB access and identifying the disposable pair, the approved development/test command is:

```bash
python manage.py reset_installation_test_fixture <DEVICE_UID> <INSTALLATION_ID>
```

Do not use `--force` until the pair has been independently checked. The command deletes only that fixture's installation records, unbinds address/customer state, restores lifecycle/inventory, and attempts a real Wi-Fi-forget command. BLE and device reachability still require physical verification afterward.

## 12. READY FOR PHYSICAL TECHNICIAN TEST

This heading is a handoff checklist, not a declaration that the fixture is already clean.

| Field | Verified state |
|---|---|
| DEVICE UID | UNKNOWN — no authenticated fixture query |
| INSTALLATION | UNVERIFIED — teardown not run |
| CUSTOMER | UNVERIFIED |
| DEVICE LIFECYCLE | UNVERIFIED |
| WI-FI | UNVERIFIED |
| BLE | UNVERIFIED |
| MQTT | UNVERIFIED |
| TEST RUN | UNVERIFIED |
| ASSIGNMENT | UNVERIFIED |
| OWNER | UNVERIFIED |
| ADDRESS | UNVERIFIED |

Before beginning, verify backend installation/assignment/customer/address/TestRun are absent, lifecycle is `READY_FOR_SHIPMENT` (the existing device equivalent of installation-ready), inventory is `READY_FOR_INSTALLATION`, Wi-Fi is forgotten, `qbox-ble-gatt.service` is active, and MQTT is offline until provisioning.

### Exact manual Technician App sequence

1. Log in.
2. Open the test installation.
3. Accept the job.
4. Mark en route.
5. Mark arrived.
6. Check in.
7. Start installation.
8. Scan the QBox identity QR.
9. BLE connect/discovery.
10. BLE authorize.
11. Run Wi-Fi scan.
12. Provision Wi-Fi.
13. Wait for QBox reconnect.
14. Verify Wi-Fi connected and Network/Internet.
15. Run MQTT.
16. Run telemetry.
17. Run internal camera.
18. Run external camera and inspect live output.
19. Run red LED and physically observe it.
20. Run green LED and physically observe it.
21. Run buzzer and physically hear it.
22. Run solenoid and physically observe actuation.
23. Run solenoid feedback and verify the sensor state.
24. Run locker open/close and physically verify both positions.
25. Run integrated system test.
26. Capture/upload required evidence.
27. Complete final inspection and customer handover.
28. Submit for QA.

After QA approval, verify atomically: order `COMPLETED`, device `ACTIVE`, correct customer/owner, and correct installation address.

## 13. Final status matrix

| Area | Status | Evidence |
|---|---|---|
| Backend installation | PASS | Server-side FSM, run-specific sequence, 48-test commissioning suite |
| Field commissioning | PASS | V4 implementation and automated workflow tests; physical execution separately blocked below |
| Test profile | PASS | Immutable migration-seeded V4 exact sequence |
| TestRun | PASS | One field run per order and historical version preservation tested |
| TestResult | PASS | Existing authoritative engine reused |
| Run Again | PASS | Controlled retest paths create new attempts |
| Attempt history | PASS | Append-only results and retry tests |
| BLE | BLOCKED | Logic/tests pass; no real phone-to-QBox BLE session in this environment |
| Wi-Fi onboarding | BLOCKED | BLE provisioning logic/tests pass; no real AP/device provisioning run |
| Wi-Fi recovery | BLOCKED | Watchdog and no-Internet regression tests pass; no radio outage test on Pi |
| Network | BLOCKED | Device executor exists; no physical network path tested |
| MQTT | BLOCKED | Dispatch/ACK integration is automated; no physical broker/device round trip performed here |
| Telemetry | BLOCKED | Contract/executor automated; no physical telemetry observation |
| Internal camera | BLOCKED | Executor tests pass; no camera attached here |
| External camera | BLOCKED | Executor tests pass; no camera attached here |
| Red LED | BLOCKED | Executor tests pass; no visual observation |
| Green LED | BLOCKED | Executor tests pass; no visual observation |
| Buzzer | BLOCKED | Executor tests pass; no audible observation |
| Solenoid | BLOCKED | Executor tests pass; no physical actuation observation |
| Solenoid feedback | BLOCKED | Executor tests pass; no feedback sensor observation |
| Locker integrated test | BLOCKED | Executor tests pass; no real locker cycle performed |
| Integrated system | BLOCKED | Automated executor path passes; no physical system run |
| Evidence | PASS | Backend evidence metadata/checksum flow retained |
| Corrective actions | PASS | API/service/rework/retest tests pass |
| Handover | PASS | Mandatory checklist/acknowledgement and final-step tests pass |
| QA | PASS | Submission/correction/finalization integration retained and tested |
| Activation | PASS | Automated lifecycle finalization test reaches ACTIVE |
| Customer binding | PASS | Backend-controlled finalization path; not technician-controlled |
| Address binding | PASS | Backend-controlled finalization path |
| Homeowner integration | PASS | Installation tests pass and V4 copy contract is complete |
| Realtime | PASS | Existing event emission path retained |
| Offline/recovery | PASS | Software watchdog behavior covered by regression tests |
| Security | PASS | Server gates, QR verification, BLE authorization, dev-profile isolation |
| Automated E2E | PASS | Backend logical happy/failure journeys and repository regressions pass; this is not physical E2E |
| Physical hardware E2E | BLOCKED | No authenticated/connected physical QBox and no technician-phone run |
| Teardown | BLOCKED | Exact fixture could not be identified; local DB authentication failed; destructive guessing was refused |
| Fresh device state | BLOCKED | Cannot verify installation/owner/address/Wi-Fi/BLE/MQTT state without teardown and physical access |

## 14. Remaining blockers and exact verification

1. Restore the local development PostgreSQL credential or point Django to the intended development database.
2. Read the exact disposable `device_uid` and `installation_id`; confirm they refer to the physical test unit.
3. Run `reset_installation_test_fixture` interactively and verify its report.
4. On the Pi, verify `hostnamectl --static` returns `qbox-dev` for the new development image, NetworkManager has forgotten the old commissioning Wi-Fi when teardown is intended, BLE GATT is active while offline, and MQTT is offline.
5. Build the development image on the supported image host, flash it, and confirm local-console login plus automatic connection to the development Wi-Fi.
6. Execute all 28 manual steps above with physical observations and retain evidence.
7. Complete QA and verify the final backend owner/address/device transaction.

Until those actions are completed, the software is ready for physical validation, but the physical fixture itself is not certified clean or ready.
