from __future__ import annotations

from typing import Any

import openhtf as htf

from . import phases
from .backend_client import BackendClient

STATION_BLE_STEP_TYPES = frozenset({"BLE_CONNECT", "BLE_AUTHORIZE", "WIFI_SCAN_BLE", "WIFI_PROVISION_BLE"})

# A step's latest attempt landing on one of these means "don't build a fresh
# phase for it" - build_plan() is called on every /test-runs/{id}/start,
# including "Resume on Station" on a run that already made real progress
# (most of it via the pre-existing direct-dispatch path, before OpenHTF was
# involved at all), and previously rebuilt+re-ran the ENTIRE plan from the
# first step every time. Confirmed live 2026-09-10: a real run that had
# already passed 13 steps got its LED_RED phase re-dispatched by Resume on
# Station, which then hit DeviceCommandInFlight/timed out because nothing
# about "resume" should be re-running already-passed hardware steps.
# REQUIRES_HUMAN belongs here too, specifically because of WIFI_FORGET: its
# failure_policy is ABORT_RUN, and it's *designed* to resolve to
# REQUIRES_HUMAN (see hardware_devices/services/command_service.py's
# _resolve_expired_test_result - the device intentionally goes offline
# before it can ack). Re-including it in a rebuilt plan means Resume on
# Station re-dispatches WIFI_FORGET, it can't ack (device is still offline
# for BLE recovery - the whole reason the operator is here), it resolves to
# REQUIRES_HUMAN again, and ABORT_RUN stops the Test right there - BLE_CONNECT
# and every phase after it never runs. Confirmed live: this was the actual
# reason Resume on Station never reached a real BLE_CONNECT/AUTHORIZE/
# WIFI_SCAN_BLE/WIFI_PROVISION_BLE sequence despite the Station's BLE stack
# working correctly in isolation.
_RESOLVED_RESULT_STATUSES = frozenset({"PASS", "WARN", "REQUIRES_HUMAN"})


class PlanBuildError(Exception):
    pass


def _latest_results_by_step(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for result in run.get("results") or []:
        step_id = str(result.get("step"))
        current = latest.get(step_id)
        if current is None or result.get("attempt_number", 0) > current.get("attempt_number", 0):
            latest[step_id] = result
    return latest


def build_plan(
    run_id: str,
    backend: BackendClient,
    *,
    ble_context: dict[str, Any] | None = None,
    on_event: phases.PhaseEventCallback | None = None,
) -> list[htf.PhaseDescriptor]:
    """
    Builds the OpenHTF phase list for a TestRun straight from its
    TestProfileVersion's ordered steps, fetched from the backend - the
    backend's TestProfileVersion is the only source of plan structure, this
    function never hardcodes a production test plan. Each step routes to
    either a BLE-native phase (STATION_BLE_STEP_TYPES) or the generic
    dispatched-step phase that drives the existing MQTT pipeline - which
    step types are physically proven today lives in which TestProfileVersion
    a run actually references (seeded backend-side), not in this routing.

    `ble_context` carries the runtime parameters the BLE-native phases need
    that are not part of a step's static definition (device address,
    identity, and - only if this run's plan actually includes WiFi
    provisioning - the operator-selected network credentials). Missing a
    required key for a step type that's actually present in the plan is a
    build-time error, not a mid-run surprise.
    """
    ble_context = ble_context or {}
    run = backend.get_test_run(run_id)
    steps = sorted(backend.get_profile_version_steps(run["profile_version"]), key=lambda s: s.get("order", 0))
    if not steps:
        raise PlanBuildError(f"TestProfileVersion {run['profile_version']} has no steps - refusing to build an empty plan")

    latest_results = _latest_results_by_step(run)

    built: list[htf.PhaseDescriptor] = []
    for step in steps:
        latest = latest_results.get(str(step["id"]))
        if latest and latest.get("status") in _RESOLVED_RESULT_STATUSES:
            continue
        step_type = step["step_type"]
        if step_type not in STATION_BLE_STEP_TYPES:
            built.append(phases.dispatched_step_phase_for(step, run_id, on_event=on_event))
            continue

        if step_type == "BLE_CONNECT":
            _require(ble_context, ["address"], step_type)
            built.append(
                phases.ble_connect_phase(
                    step, run_id,
                    ble_address=ble_context["address"],
                    expected_device_uid=ble_context.get("expected_device_uid"),
                    on_event=on_event,
                )
            )
        elif step_type == "BLE_AUTHORIZE":
            _require(ble_context, ["session_id", "token", "expires_at"], step_type)
            built.append(
                phases.ble_authorize_phase(
                    step, run_id,
                    session_id=ble_context["session_id"],
                    token=ble_context["token"],
                    expires_at=ble_context["expires_at"],
                    on_event=on_event,
                )
            )
        elif step_type == "WIFI_SCAN_BLE":
            built.append(phases.wifi_scan_ble_phase(step, run_id, on_event=on_event))
        elif step_type == "WIFI_PROVISION_BLE":
            _require(ble_context, ["wifi_ssid", "wifi_password"], step_type)
            built.append(
                phases.wifi_provision_ble_phase(
                    step, run_id,
                    ssid=ble_context["wifi_ssid"],
                    password=ble_context["wifi_password"],
                    on_event=on_event,
                )
            )
        else:  # pragma: no cover - STATION_BLE_STEP_TYPES kept in sync with this if/elif chain
            raise PlanBuildError(f"Unhandled BLE-native step_type {step_type!r}")

    if not built:
        raise PlanBuildError(
            f"TestRun {run_id} has nothing left to run on the Station - every step already has a "
            "resolved result (PASS/WARN/REQUIRES_HUMAN). Nothing to resume."
        )
    return built


def _require(context: dict[str, Any], keys: list[str], step_type: str) -> None:
    missing = [k for k in keys if not context.get(k)]
    if missing:
        raise PlanBuildError(f"Step {step_type} requires {missing} in ble_context but none were provided")
