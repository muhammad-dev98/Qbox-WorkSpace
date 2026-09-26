from __future__ import annotations

import asyncio
import threading

import openhtf as htf
import pytest

from conftest import FakeBackendClient, FakeBleDevice
from station_agent.openhtf.plugs import BackendClientPlug, BleStationPlug


@pytest.fixture
def ble_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)


def _wire_ble_plug(monkeypatch, ble_loop, fake_device: FakeBleDevice):
    # BleStationPlug.connect() constructs a fresh QBoxBleDevice itself
    # (real bleak/BlueZ) - the fake must replace that constructor for tests
    # that call connect(), and also pre-seed self._device for tests that
    # exercise authorize()/scan_wifi()/configure_wifi() on an
    # already-connected plug without going through connect() first.
    monkeypatch.setattr(BleStationPlug, "loop", ble_loop)
    monkeypatch.setattr("station_agent.openhtf.plugs.QBoxBleDevice", lambda *a, **kw: fake_device)

    real_init = BleStationPlug.__init__

    def _init(self):
        real_init(self)
        self._device = fake_device

    monkeypatch.setattr(BleStationPlug, "__init__", _init)


def _wire_backend_plug(monkeypatch, backend: FakeBackendClient):
    monkeypatch.setattr(BackendClientPlug, "__init__", lambda self: setattr(self, "client", backend))


def test_ble_connect_phase_success_records_physical_evidence(monkeypatch, ble_loop, sample_step):
    from station_agent.openhtf.phases import ble_connect_phase

    step = sample_step("BLE_CONNECT", timeout_seconds=5)
    backend = FakeBackendClient(run={"id": "run-1"}, steps=[step])
    _wire_backend_plug(monkeypatch, backend)
    _wire_ble_plug(monkeypatch, ble_loop, FakeBleDevice())

    phase = ble_connect_phase(step, "run-1", ble_address="AA:BB:CC:DD:EE:FF", expected_device_uid=None)
    result = htf.Test(phase).execute(test_start=lambda: "DUT-1")

    assert result is True
    assert backend.begin_step_calls == [("run-1", step["id"])]
    assert len(backend.submit_result_calls) == 1
    submitted = backend.submit_result_calls[0]
    assert submitted["status"] == "PASS"
    assert submitted["evidence_type"] == "PHYSICAL"


def test_ble_connect_phase_failure_maps_to_fail_not_physical(monkeypatch, ble_loop, sample_step):
    from station_agent.openhtf.phases import ble_connect_phase

    step = sample_step("BLE_CONNECT", timeout_seconds=5)
    backend = FakeBackendClient(run={"id": "run-1"}, steps=[step])
    _wire_backend_plug(monkeypatch, backend)
    _wire_ble_plug(monkeypatch, ble_loop, FakeBleDevice(raise_on="connect", error_code="BLE_DEVICE_NOT_FOUND"))

    phase = ble_connect_phase(step, "run-1", ble_address="AA:BB:CC:DD:EE:FF", expected_device_uid=None)
    htf.Test(phase).execute(test_start=lambda: "DUT-1")

    submitted = backend.submit_result_calls[0]
    assert submitted["status"] == "FAIL"
    assert submitted["evidence_type"] == "NOT_EXECUTED"
    assert submitted["error_code"] == "BLE_DEVICE_NOT_FOUND"


def test_ble_adapter_not_found_maps_to_requires_external_equipment(monkeypatch, ble_loop, sample_step):
    from station_agent.openhtf.phases import ble_connect_phase

    step = sample_step("BLE_CONNECT", timeout_seconds=5)
    backend = FakeBackendClient(run={"id": "run-1"}, steps=[step])
    _wire_backend_plug(monkeypatch, backend)
    _wire_ble_plug(monkeypatch, ble_loop, FakeBleDevice(raise_on="connect", error_code="BLE_ADAPTER_NOT_FOUND"))

    phase = ble_connect_phase(step, "run-1", ble_address="AA:BB:CC:DD:EE:FF", expected_device_uid=None)
    htf.Test(phase).execute(test_start=lambda: "DUT-1")

    assert backend.submit_result_calls[0]["status"] == "REQUIRES_EXTERNAL_EQUIPMENT"


def test_wifi_provision_ble_phase_never_records_password(monkeypatch, ble_loop, sample_step):
    from station_agent.openhtf.phases import wifi_provision_ble_phase

    step = sample_step("WIFI_PROVISION_BLE", timeout_seconds=5)
    backend = FakeBackendClient(run={"id": "run-1"}, steps=[step])
    _wire_backend_plug(monkeypatch, backend)
    _wire_ble_plug(monkeypatch, ble_loop, FakeBleDevice(configure_result="CONNECTED"))

    phase = wifi_provision_ble_phase(step, "run-1", ssid="MyNetwork", password="super-secret-password")
    result = htf.Test(phase).execute(test_start=lambda: "DUT-1")

    assert result is True
    submitted = backend.submit_result_calls[0]
    assert submitted["status"] == "PASS"
    serialized = str(submitted)
    assert "super-secret-password" not in serialized
    assert submitted["actual_values"]["ssid"] == "MyNetwork"
    assert "latency_ms" in submitted["actual_values"]


def test_ble_native_phase_crash_safe_always_submits_result(monkeypatch, ble_loop, sample_step):
    """
    Even if the BLE call raises something other than StationBleError, the
    phase must still resolve the RUNNING TestResult it created via
    begin_step() - never leave it stuck.
    """
    from station_agent.openhtf.phases import ble_connect_phase

    step = sample_step("BLE_CONNECT", timeout_seconds=5)
    backend = FakeBackendClient(run={"id": "run-1"}, steps=[step])
    _wire_backend_plug(monkeypatch, backend)

    class ExplodingDevice(FakeBleDevice):
        async def connect(self, timeout: float = 20.0):
            raise RuntimeError("unexpected bug")

    _wire_ble_plug(monkeypatch, ble_loop, ExplodingDevice())

    phase = ble_connect_phase(step, "run-1", ble_address="AA:BB:CC:DD:EE:FF", expected_device_uid=None)
    htf.Test(phase).execute(test_start=lambda: "DUT-1")

    assert backend.begin_step_calls == [("run-1", step["id"])]
    assert len(backend.submit_result_calls) == 1
    submitted = backend.submit_result_calls[0]
    assert submitted["status"] == "FAIL"
    assert submitted["error_code"] == "STATION_PHASE_EXCEPTION"
