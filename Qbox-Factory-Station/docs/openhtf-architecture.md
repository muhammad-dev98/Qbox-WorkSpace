# OpenHTF on the Factory Station

## Status of this document

Covers Phases 1-4 of the production factory-testing roadmap: backend station identity/auth (Phase 1), the OpenHTF execution foundation - plan/phase/plug machinery and the local Station↔Panel auth gate (Phase 2), the backend endpoints this Station's `BackendClient`/`plan_builder` depend on (Phase 3), and the BLE-native `TestStepType` enum values now existing backend-side with a seeded diagnostic profile exercising them (Phase 4). It does **not** cover the full production test catalogue (identity/system/WiFi/Ethernet/MQTT/telemetry/streaming/burn-in/security steps), device/station locking, or the backend certification gate - those are later phases in the same roadmap and are explicitly not implemented yet. Nothing here should be read as "production ready" on its own.

## Why OpenHTF here, and what it is not

OpenHTF is the **orchestration and sequencing layer that runs on the Factory Station** - it decides what phase runs next, records measurements/attachments, and enforces timeouts/failure policy. It is explicitly **not** a replacement for:

- the existing, physically-verified MQTT `RUN_TEST` dispatch pipeline (device-side GPIO/camera/storage executors in `Qbox-Hardware`) - a "dispatched" OpenHTF phase drives that pipeline (calls `dispatch-next-step`, polls for the result), it does not reimplement it;
- the backend's `TestRun`/`TestResult`/`TestExecutionIngestService` data model - the backend remains the sole source of truth for results, evidence, and audit; the Station's local OpenHTF JSON record (see below) is a debugging/audit artifact only;
- the existing native-BLE stack (`station_agent/ble_client.py`, `bleak`/BlueZ) - BLE-native OpenHTF phases call it exactly as the pre-existing `/devices/*` HTTP handlers already did, unmodified.

## Component diagram

```
Factory Panel (browser)
   │ HTTP + WS, Authorization: Bearer <operator JWT>
   ▼
station_agent/server.py (aiohttp, 127.0.0.1:<port>)
   │  /devices/*         -- existing BLE bridge, untouched in this phase
   │  /test-runs/*/start │ /status │ /abort │ /pause │ /resume  -- new
   │  auth middleware -> station_agent/local_auth.py -> backend GET /auth/profile
   ▼
station_agent/openhtf/runner.py: StationTestRunner
   │  owns: 1 dedicated BLE asyncio loop+thread, 1-worker executor for openhtf.Test.execute()
   ▼
openhtf.Test(*phases)  -- built per-run by plan_builder.build_plan()
   │
   ├── dispatched-step phase (any non-BLE step_type)
   │      -> BackendClientPlug -> backend_client.BackendClient
   │      -> POST /test-runs/{id}/dispatch-next-step/  (existing, Phase 3 wiring)
   │      -> poll GET /test-runs/{id}/  until this step's TestResult is terminal
   │      -> UNCHANGED MQTT RUN_TEST pipeline underneath
   │
   └── BLE-native phase (BLE_CONNECT / BLE_AUTHORIZE / WIFI_SCAN_BLE / WIFI_PROVISION_BLE)
          -> BackendClientPlug.begin_step()  (new, Phase 3 wiring)
          -> BleStationPlug -> station_agent/ble_client.py (unmodified)
          -> BackendClientPlug.submit_result()  (new, Phase 3 wiring), always in a finally
```

## Step-type -> phase-kind routing

`station_agent/openhtf/plan_builder.py`'s `STATION_BLE_STEP_TYPES` frozenset is the **only** place this routing decision lives:

```python
STATION_BLE_STEP_TYPES = frozenset({"BLE_CONNECT", "BLE_AUTHORIZE", "WIFI_SCAN_BLE", "WIFI_PROVISION_BLE"})
```

Every other `step_type` present in a `TestProfileVersion` is routed to the generic dispatched-step phase. Which step types are physically proven today is **not** encoded in this code at all - it lives entirely in which `TestProfileVersion` a given `TestRun` actually references, seeded backend-side. The Station never hardcodes a production test plan; `plan_builder.build_plan(run_id, backend)` always fetches the run's steps from the backend.

## Failure-policy -> PhaseResult mapping

| `TestStepDefinition.failure_policy` | Non-passing step outcome |
|---|---|
| `ABORT_RUN` | `PhaseResult.STOP` - the whole `openhtf.Test` stops, no further phases run |
| `MARK_FAILED_CONTINUE` / `CONTINUE` | `PhaseResult.CONTINUE` - failure is recorded, the run proceeds |

A passing outcome (`PASS` or `WARN`) always continues regardless of policy.

## Pause/resume safety

`station_agent/openhtf/phases.py` defines `UNSAFE_TO_PAUSE_STEP_TYPES` - currently `{"WIFI_PROVISION_BLE"}` (a half-sent WiFi credential is worse than either finishing or cleanly failing). `StationTestRunner.request_pause()` checks the *currently executing* step's type against this set and raises `PauseRejectedError` (surfaced as HTTP 409) if it's unsafe; otherwise it sets a cooperative flag honored at the next phase boundary. This list must be extended whenever a later phase adds another actuation/credential/security-critical step type - it is not automatically safe by default in the sense of being reviewed, only in the sense of not being in the set yet.

Note: OpenHTF's `PhaseDescriptor` is an `attrs` slotted class and does not support arbitrary custom attributes, so this is a step-type-keyed set checked by the runner, not a per-phase-object flag - functionally equivalent, verified directly against the installed `openhtf==1.6.1` API before choosing this approach.

## Station identity and local Station↔Panel authentication

Two **separate** credentials exist in this process, and they must never cross:

1. **Station -> Backend**: `X-Station-Key: <key_id>.<secret>`, issued via `manage.py issue_station_key <station_code>` on the backend (Phase 1), loaded from `--station-key`/`QBOX_STATION_KEY`/`~/.config/qbox-factory-station/credentials.json` (`station_agent/openhtf/config.py`). Attached only by `backend_client.py` on outbound Station->backend calls.
2. **Panel -> Station (local API)**: the operator's own existing backend JWT (`Authorization: Bearer <token>`), the same token the Panel already holds from logging into the backend. `station_agent/local_auth.py`'s `OperatorAuthenticator` validates it by calling the backend's live `GET /auth/profile` endpoint (confirmed via source read of `authentication/api/auth_urls.py`/`profile_view.py`) and caches a positive result until (a bounded ceiling before) the token's own `exp`. **Why not verify locally**: the backend's `SIMPLE_JWT` config carries no `SIGNING_KEY`/`ALGORITHM` override, so `rest_framework_simplejwt`'s HS256 default applies - a symmetric secret. A Station holding that secret could forge any operator's token, which is strictly worse than the scoped station-key credential it already holds. So every local-API call is checked against the backend on cache miss instead.

The Station's local HTTP API previously had no authentication at all (loopback-binding only). It now requires a valid operator Bearer token on every route (`_auth_middleware` in `server.py`) when an `authenticator` is configured; `app["authenticator"]` is `None` only when no backend credentials were supplied (e.g. `--no-openhtf`), in which case the pre-existing BLE-only bridge behavior is preserved unauthenticated, matching this repo's original scope.

## Auditability: local record vs. backend source of truth

Each run produces a local OpenHTF JSON record at `~/.local/share/qbox-factory-station/openhtf-records/{run_id}.json` (`openhtf.output.callbacks.json_factory.OutputToJSON`), useful for local debugging and station-side audit. **This is never authoritative** - the backend's `TestRun`/`TestResult`/`FactoryAuditEvent` rows are the only source of truth for certification and history. OpenHTF's own bundled web/Station-API server (`openhtf.output.servers.station_server`) is never constructed - confirmed it is opt-in, not started implicitly by `Test.execute()`, so simply never importing/using it avoids a second, redundant local HTTP surface without needing any config flag.

## Local HTTP API (new routes, this phase)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/test-runs/{run_id}/start` | operator Bearer | body: `{"ble_context": {...}}` (address/expected_device_uid/session/wifi credentials as needed by the run's plan). 202 on accept, 409 `STATION_BUSY` if a run is already active, 503 if no backend credentials configured. |
| GET | `/test-runs/{run_id}/status` | operator Bearer | `{run_id, phase, station_status, result, error}`. `IDLE` if unknown/not this station's active run. |
| POST | `/test-runs/{run_id}/abort` | operator Bearer | Best-effort: notifies the backend's existing cancel endpoint; an in-flight actuation phase finishes to a safe state before honoring it. |
| POST | `/test-runs/{run_id}/pause` | operator Bearer | 409 `PAUSE_NOT_SAFE` if the current phase is in `UNSAFE_TO_PAUSE_STEP_TYPES`. |
| POST | `/test-runs/{run_id}/resume` | operator Bearer | |

Existing `/devices/*`, `/station/status`, `/events` routes are unchanged in shape, now behind the same operator-auth middleware.

## Backend endpoints this phase's `BackendClient` calls

All under `X-Station-Key` auth (Phase 1's `StationAPIKeyAuthentication`). As of Phase 3, every endpoint `BackendClient` calls is real and deployed, not just planned: `dispatch-next-step`/test-run detail/list/cancel and the profile-version steps endpoint were already live; `POST /test-runs/{id}/steps/{step_id}/begin/` (`TestRunBeginStepAPIView`) and `POST /test-runs/{id}/results/{result_id}/submit/` (`TestRunSubmitStationResultAPIView`) are now implemented server-side too, both `StationAPIKeyAuthentication` + `IsStationPrincipal`-only, routing through `TestRunService.begin_step()` and `TestExecutionIngestService.ingest_direct()` (which share the same idempotent `(test_run, step, attempt_number)` upsert the MQTT command-ack path uses - see `Qbox-Backend/docs/factory/factory-api.md` for the full request/response shapes once documented there).

Phase 4 added the four BLE-native `TestStepType` values backend-side (`BLE_CONNECT`, `BLE_AUTHORIZE`, `WIFI_SCAN_BLE`, `WIFI_PROVISION_BLE`) - these are exactly the strings `plan_builder.STATION_BLE_STEP_TYPES` already used since Phase 2, written ahead of the backend enum existing. A seed migration (`factory_ops/migrations/0012_seed_ble_native_diagnostic_steps.py`) publishes a v3 of the existing "Component Diagnostics" profile including them, so an operator can exercise BLE connect/authorize/WiFi-scan/WiFi-provision individually from the Factory Panel Components page. This is **not** the full production test plan (that's a later roadmap phase) - just enough to prove the enum and the Station's routing agree.

## What is verified (as of Phase 4)

- Full Station-side unit test suite (41 tests) passes against the real, installed `openhtf==1.6.1` package - not a mock of OpenHTF itself. Confirms: dynamic plan construction from step lists, dispatched-phase poll/timeout/backend-outage-retry behavior, `ABORT_RUN` vs `MARK_FAILED_CONTINUE` phase-result mapping, BLE-native phase success/failure/adapter-not-found mapping, crash-safety (a phase-internal bug still resolves the RUNNING result rather than leaving it stuck), WiFi credentials never appearing in any recorded measurement/attachment, the local auth middleware's accept/reject behavior, and the new HTTP routes' request/response shapes.
- Core OpenHTF mechanics (plug class-attribute configuration pattern, `@htf.measures`/`test.attach`/`PhaseResult`, `Test.execute()` not starting any bundled web server, `OutputToJSON` writing a local record) were independently verified against the real installed package before being relied on in design, not assumed from documentation.
- Backend-side: 227/227 tests pass on a real deployment (`factory_ops` + `hardware_devices`, real Postgres, no mocked DB), including new coverage in `Qbox-Backend/factory_ops/tests/test_station_test_run_api.py` that drives the actual `BLE_CONNECT`/`BLE_AUTHORIZE`/`WIFI_SCAN_BLE`/`WIFI_PROVISION_BLE` enum values (not a stand-in step type) through the real begin/submit endpoints end to end, confirming a failed required BLE step fails the run and a fully-passing sequence passes it.
- Not yet exercised: the Station's `BackendClient`/`plan_builder`/BLE phases have not been run against this real backend over the network in this session (no live Station process + live backend + live BLE device were available together) - the two sides were verified independently, against the same contract, not against each other live.

## What is NOT yet verified

- End-to-end against a real backend or real BLE hardware - no physical device was available in this session for that.
- The `GET /auth/profile` introspection call's exact latency/availability characteristics under real network conditions.

**Phase 5 update**: the Factory Panel side of this local-auth gate is now real too - `Qbox-Factory-Panel/src/lib/station/stationClient.ts` attaches the operator's existing backend access token as `Authorization: Bearer` on every call to this Station's local API (verified by unit test that no `X-Station-Key`-shaped header is ever sent from the browser). Phase 5 also added the Panel's `TestRunDetailPage` "Start on Station"/"Abort" buttons, which call this Station's `/test-runs/{id}/start` and `/test-runs/{id}/abort` - still not exercised against a real running Station process in this session, but the contract on both ends now matches.
- Everything from Phase 4 onward in the roadmap (device/station locking, certification gate, full production test catalogue, durable crash-recovery spool, real-device acceptance run).
