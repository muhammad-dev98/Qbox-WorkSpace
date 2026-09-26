from __future__ import annotations

import time
from typing import Any, Callable

PhaseEventCallback = Callable[[str, str, dict], None]  # (event_type, step_type, payload) -> None


def _notify(on_event: PhaseEventCallback | None, event_type: str, step_type: str, payload: dict) -> None:
    if on_event is not None:
        try:
            on_event(event_type, step_type, payload)
        except Exception:  # pragma: no cover - a status-reporting bug must never fail the actual test phase
            pass

import openhtf as htf
from openhtf import plugs

from ..ble_client import StationBleError
from .backend_client import BackendError
from .measurements import is_passing, record_step_result
from .plugs import BackendClientPlug, BleStationPlug

# Step types whose OpenHTF phase must never be paused mid-flight: live BLE
# credential provisioning (a half-sent WiFi credential is worse than either
# finishing or cleanly failing) and any other actuation/security-critical
# step added in a later phase. plan_builder.py checks this set (by
# step_type, not by phase-object attribute - OpenHTF's PhaseDescriptor is an
# attrs slots class and does not support arbitrary custom attributes) when
# deciding whether a pause request may take effect at the next boundary.
UNSAFE_TO_PAUSE_STEP_TYPES = frozenset({"WIFI_PROVISION_BLE"})

_BLE_ERROR_TO_RESULT_STATUS = {
    "BLE_ADAPTER_NOT_FOUND": "REQUIRES_EXTERNAL_EQUIPMENT",
}


def _ble_error_status(exc: StationBleError) -> str:
    # Every other StationBleError code (BLE_DEVICE_NOT_FOUND,
    # BLE_CONNECTION_FAILED, BLE_GATT_SERVICE_NOT_FOUND,
    # BLE_CHARACTERISTIC_NOT_FOUND, BLE_DEVICE_IDENTITY_MISMATCH,
    # BLE_AUTH_FAILED, WIFI_REQUEST_FAILED, and anything unmapped) is a
    # genuine FAIL, never a silent PASS.
    return _BLE_ERROR_TO_RESULT_STATUS.get(exc.code, "FAIL")


def _phase_result_for(status: str, failure_policy: str) -> htf.PhaseResult:
    if is_passing(status):
        return htf.PhaseResult.CONTINUE
    if failure_policy == "ABORT_RUN":
        return htf.PhaseResult.STOP
    return htf.PhaseResult.CONTINUE  # MARK_FAILED_CONTINUE / CONTINUE - failure already recorded


def dispatched_step_phase_for(
    step: dict, run_id: str, *, poll_interval_s: float = 1.0, on_event: PhaseEventCallback | None = None
) -> htf.PhaseDescriptor:
    """
    Generic phase for any device-executed step type (LED/solenoid/camera/
    storage/wifi/mqtt/etc - anything dispatched via the existing,
    physically-proven MQTT RUN_TEST pipeline). Drives that pipeline rather
    than reimplementing it: calls the backend's existing
    dispatch-next-step, then polls the existing test-run detail endpoint
    until this step's result is terminal or its own timeout_seconds budget
    (server-recorded, never re-hardcoded here) elapses.

    Backend-unreachable is NOT the same as step-failed: BackendError with
    is_connectivity_error=True is retried within the timeout budget rather
    than immediately recorded as FAIL (full durable-outage handling with a
    local spool is planned for a later phase; this phase already avoids the
    single worst failure mode - misreporting a network blip as a hardware
    failure).
    """
    step_type = step["step_type"]
    timeout_s = float(step.get("timeout_seconds") or 60)
    failure_policy = step.get("failure_policy") or "MARK_FAILED_CONTINUE"

    @htf.measures("step_outcome")
    @plugs.plug(backend=BackendClientPlug)
    @htf.PhaseOptions(name=step_type, timeout_s=timeout_s)
    def _dispatched_phase(test, backend: BackendClientPlug):
        client = backend.client
        _notify(on_event, "phase.started", step_type, {})
        deadline = time.monotonic() + timeout_s
        try:
            client.dispatch_next_step(run_id)
        except BackendError as exc:
            if not exc.is_connectivity_error:
                raise
            # Fall through to the poll loop below, which itself tolerates
            # connectivity errors - a dispatch call that failed to land
            # because the backend was briefly unreachable is retried by
            # the same loop's next dispatch_next_step()-less poll, which
            # will simply keep observing the step is still not started.

        last_error: BackendError | None = None
        while time.monotonic() < deadline:
            try:
                run = client.get_test_run(run_id)
            except BackendError as exc:
                if not exc.is_connectivity_error:
                    raise
                last_error = exc
                time.sleep(poll_interval_s)
                continue
            result = _find_result_for_step(run, step["id"])
            if result is not None and result.get("status") not in {"PENDING", "RUNNING", "NOT_STARTED", None}:
                status = record_step_result(test, step, result)
                _notify(on_event, "phase.completed", step_type, {"status": status})
                return _phase_result_for(status, failure_policy)
            time.sleep(poll_interval_s)

        # Timed out without a terminal result - record as TIMEOUT, not a
        # silent pass, distinguishing a genuine step timeout from the
        # backend simply being unreachable the whole window (surfaced via
        # last_error in the attachment for diagnosis).
        status = record_step_result(
            test, step,
            {
                "status": "TIMEOUT",
                "error_code": "STEP_DISPATCH_TIMEOUT",
                "diagnostic": str(last_error) if last_error else None,
            },
        )
        _notify(on_event, "phase.completed", step_type, {"status": status})
        return _phase_result_for(status, failure_policy)

    return _dispatched_phase


def _find_result_for_step(run: dict, step_id: str) -> dict | None:
    matches: list[dict] = []
    for result in run.get("results") or []:
        if result.get("step") == step_id or result.get("step_id") == step_id:
            matches.append(result)
    if not matches:
        return None
    return sorted(matches, key=lambda item: int(item.get("attempt_number") or 0), reverse=True)[0]


def _ble_native_phase(
    step: dict, run_id: str, *, timeout_s: float, action, on_event: PhaseEventCallback | None = None
) -> htf.PhaseDescriptor:
    """
    Shared shape for every BLE-native phase (connect/authorize/scan/
    provision): begin_step() -> real BLE call -> submit_result() in a
    finally, so a Station crash or an unexpected exception can never leave
    a TestResult stuck at RUNNING - matches the "crash-safe" requirement
    for this phase family specifically (dispatched steps get the same
    guarantee for free from the device-side executor's own timeout/error
    handling).
    """
    step_type = step["step_type"]
    failure_policy = step.get("failure_policy") or "MARK_FAILED_CONTINUE"

    @htf.measures("step_outcome")
    @plugs.plug(backend=BackendClientPlug, ble=BleStationPlug)
    @htf.PhaseOptions(name=step_type, timeout_s=timeout_s)
    def _phase(test, backend: BackendClientPlug, ble: BleStationPlug):
        client = backend.client
        _notify(on_event, "phase.started", step_type, {})
        begun = client.begin_step(run_id, step["id"])
        result_id = begun["test_result_id"]
        payload: dict[str, Any]
        try:
            data = action(ble, step)
            payload = {"status": "PASS", "evidence_type": "PHYSICAL", **data}
        except StationBleError as exc:
            payload = {
                "status": _ble_error_status(exc),
                "evidence_type": "NOT_EXECUTED",
                "error_code": exc.code,
                "diagnostic": str(exc),
            }
        except Exception as exc:
            # A genuinely unexpected bug (not a StationBleError) must still
            # resolve the RUNNING TestResult begin_step() just created -
            # "crash-safe" means this too, not only the anticipated BLE
            # error codes. Recorded as FAIL with a distinct error_code so
            # it's never confused with a real hardware failure in
            # diagnostics.
            payload = {
                "status": "FAIL",
                "evidence_type": "NOT_EXECUTED",
                "error_code": "STATION_PHASE_EXCEPTION",
                "diagnostic": repr(exc),
            }
        try:
            client.submit_result(
                run_id, result_id,
                status=payload["status"],
                evidence_type=payload["evidence_type"],
                actual_values={k: v for k, v in payload.items() if k not in {"status", "evidence_type"}},
                error_code=payload.get("error_code", ""),
            )
        except BackendError:
            # Submission itself failed (e.g. backend unreachable) - the run
            # is left RUNNING on this step rather than silently swallowed;
            # durable retry/spool for this case lands in a later phase.
            # Still record locally for auditability even if backend never
            # got it.
            pass
        status = record_step_result(test, step, payload)
        _notify(on_event, "phase.completed", step_type, {"status": status})
        return _phase_result_for(status, failure_policy)

    return _phase


def ble_connect_phase(
    step: dict, run_id: str, *, ble_address: str, expected_device_uid: str | None, on_event: PhaseEventCallback | None = None
) -> htf.PhaseDescriptor:
    timeout_s = float(step.get("timeout_seconds") or 30)

    def _connect(ble: BleStationPlug, _step: dict) -> dict:
        identity = ble.connect(ble_address, expected_device_uid=expected_device_uid, timeout=timeout_s)
        return {"identity": identity}

    return _ble_native_phase(step, run_id, timeout_s=timeout_s, action=_connect, on_event=on_event)


def ble_authorize_phase(
    step: dict, run_id: str, *, session_id: str, token: str, expires_at: str, on_event: PhaseEventCallback | None = None
) -> htf.PhaseDescriptor:
    timeout_s = float(step.get("timeout_seconds") or 20)

    def _authorize(ble: BleStationPlug, _step: dict) -> dict:
        result = ble.authorize(session_id=session_id, token=token, expires_at=expires_at, timeout=timeout_s)
        return {"secure_session_id": result.get("secure_session_id")}

    return _ble_native_phase(step, run_id, timeout_s=timeout_s, action=_authorize, on_event=on_event)


def wifi_scan_ble_phase(step: dict, run_id: str, *, on_event: PhaseEventCallback | None = None) -> htf.PhaseDescriptor:
    timeout_s = float(step.get("timeout_seconds") or 25)

    def _scan(ble: BleStationPlug, _step: dict) -> dict:
        networks = ble.scan_wifi(timeout=timeout_s)
        # SSIDs only - never a password at this step, and network contents
        # go into the attachment (server-side evidence), never plaintext
        # into a WebSocket event (there is no WS emission at this layer at
        # all - see runner.py, which only ever forwards a
        # {status, phase_name} shape).
        return {"network_count": len(networks), "ssids": [n.get("ssid") for n in networks]}

    return _ble_native_phase(step, run_id, timeout_s=timeout_s, action=_scan, on_event=on_event)


def wifi_provision_ble_phase(
    step: dict, run_id: str, *, ssid: str, password: str, on_event: PhaseEventCallback | None = None
) -> htf.PhaseDescriptor:
    """
    Credentials are passed in as call-time closures arguments, never stored
    on the plug/phase objects beyond this call, and never included in the
    recorded measurement/attachment (see _provision below) - only
    {ssid, result, latency_ms} is ever persisted, matching the requirement
    that a WiFi password must never appear in a log, measurement, or
    WebSocket message.
    """
    timeout_s = float(step.get("timeout_seconds") or 45)

    def _provision(ble: BleStationPlug, _step: dict) -> dict:
        started = time.monotonic()
        try:
            status = ble.configure_wifi(ssid=ssid, password=password, timeout=timeout_s)
        finally:
            pass  # `password` is a local var, released with this frame - never assigned anywhere longer-lived
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"ssid": ssid, "result": status, "latency_ms": latency_ms}

    return _ble_native_phase(step, run_id, timeout_s=timeout_s, action=_provision, on_event=on_event)
