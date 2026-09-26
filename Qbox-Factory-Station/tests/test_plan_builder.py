from __future__ import annotations

import pytest

from conftest import FakeBackendClient
from station_agent.openhtf import plan_builder
from station_agent.openhtf.plan_builder import PlanBuildError


def test_build_plan_routes_dispatched_and_ble_steps_in_order(sample_step):
    steps = [
        sample_step("LED_RED", order=1),
        sample_step("BLE_CONNECT", order=2),
        sample_step("WIFI_SCAN_BLE", order=3),
        sample_step("STORAGE", order=4),
    ]
    backend = FakeBackendClient(run={"id": "run-1", "profile_version": "v1"}, steps=steps)

    phases = plan_builder.build_plan(
        "run-1", backend,
        ble_context={"address": "AA:BB:CC:DD:EE:FF"},
    )

    assert [p.options.name for p in phases] == ["LED_RED", "BLE_CONNECT", "WIFI_SCAN_BLE", "STORAGE"]


def test_build_plan_empty_steps_raises():
    backend = FakeBackendClient(run={"id": "run-1", "profile_version": "v1"}, steps=[])
    with pytest.raises(PlanBuildError):
        plan_builder.build_plan("run-1", backend)


def test_build_plan_missing_ble_context_raises(sample_step):
    steps = [sample_step("BLE_CONNECT", order=1)]
    backend = FakeBackendClient(run={"id": "run-1", "profile_version": "v1"}, steps=steps)
    with pytest.raises(PlanBuildError):
        plan_builder.build_plan("run-1", backend, ble_context={})


def test_build_plan_wifi_provision_requires_credentials(sample_step):
    steps = [sample_step("WIFI_PROVISION_BLE", order=1)]
    backend = FakeBackendClient(run={"id": "run-1", "profile_version": "v1"}, steps=steps)
    with pytest.raises(PlanBuildError):
        plan_builder.build_plan("run-1", backend, ble_context={"wifi_ssid": "Net"})  # missing wifi_password


def test_build_plan_orders_by_step_order_field(sample_step):
    steps = [
        sample_step("STORAGE", order=3),
        sample_step("LED_RED", order=1),
        sample_step("LED_GREEN", order=2),
    ]
    backend = FakeBackendClient(run={"id": "run-1", "profile_version": "v1"}, steps=steps)
    phases = plan_builder.build_plan("run-1", backend)
    assert [p.options.name for p in phases] == ["LED_RED", "LED_GREEN", "STORAGE"]


def test_build_plan_skips_steps_with_a_resolved_result(sample_step):
    # Regression test for a real bug found live 2026-09-10: "Resume on
    # Station" rebuilt the ENTIRE plan from the first step on every call,
    # including steps that had already passed via the pre-existing direct-
    # dispatch path. Worse, WIFI_FORGET (failure_policy=ABORT_RUN, designed
    # to resolve to REQUIRES_HUMAN because the device goes offline before it
    # can ack) got re-dispatched on every resume, re-resolved to
    # REQUIRES_HUMAN, and ABORT_RUN stopped the whole Test before BLE_CONNECT
    # (which comes after it in step order) ever ran.
    steps = [
        sample_step("LED_RED", order=1),
        sample_step("WIFI_FORGET", order=2, failure_policy="ABORT_RUN"),
        sample_step("BLE_CONNECT", order=3),
    ]
    backend = FakeBackendClient(
        run={"id": "run-1", "profile_version": "v1"},
        steps=steps,
        results_by_step={
            "step-led_red": [{"status": "PASS", "attempt_number": 1, "_delivered": True}],
            "step-wifi_forget": [{"status": "REQUIRES_HUMAN", "attempt_number": 2, "_delivered": True}],
        },
    )

    phases = plan_builder.build_plan(
        "run-1", backend,
        ble_context={"address": "AA:BB:CC:DD:EE:FF"},
    )

    assert [p.options.name for p in phases] == ["BLE_CONNECT"]


def test_build_plan_reruns_a_step_with_no_resolved_result(sample_step):
    # A step with no result at all, or a genuinely-failed one, must still be
    # built - only PASS/WARN/REQUIRES_HUMAN mean "don't re-run this".
    steps = [sample_step("STORAGE", order=1)]
    backend = FakeBackendClient(
        run={"id": "run-1", "profile_version": "v1"},
        steps=steps,
        results_by_step={"step-storage": [{"status": "FAIL", "attempt_number": 1, "_delivered": True}]},
    )
    phases = plan_builder.build_plan("run-1", backend)
    assert [p.options.name for p in phases] == ["STORAGE"]


def test_build_plan_raises_when_everything_already_resolved(sample_step):
    steps = [sample_step("LED_RED", order=1)]
    backend = FakeBackendClient(
        run={"id": "run-1", "profile_version": "v1"},
        steps=steps,
        results_by_step={"step-led_red": [{"status": "PASS", "attempt_number": 1, "_delivered": True}]},
    )
    with pytest.raises(PlanBuildError):
        plan_builder.build_plan("run-1", backend)
