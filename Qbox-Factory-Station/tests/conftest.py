from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from station_agent.ble_client import StationBleError

# Loads Qbox-Hardware's REAL device-side secure_protocol.py directly by file
# path - not via `import qbox_platform...`, which would pull in that
# package's own __init__ chain (dbus_next, paho-mqtt, etc. as installed in
# ITS venv, not this station agent's) just to reach one dependency-free leaf
# module. This proves the station agent's independent crypto port matches
# the actual device implementation byte-for-byte, without coupling this
# project's test environment to Qbox-Hardware's runtime dependencies.
_SECURE_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[2] / "Qbox-Hardware" / "platform" / "qbox_platform" / "bluetooth" / "secure_protocol.py"
)


@pytest.fixture(scope="session")
def device_secure_protocol() -> types.ModuleType:
    if not _SECURE_PROTOCOL_PATH.is_file():
        pytest.skip(f"Qbox-Hardware not checked out alongside this repo (expected {_SECURE_PROTOCOL_PATH})")
    spec = importlib.util.spec_from_file_location("device_secure_protocol", _SECURE_PROTOCOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeBackendClient:
    """
    Duck-typed stand-in for station_agent.openhtf.backend_client.BackendClient -
    plan_builder/phases only call methods on it, never isinstance-check the
    type, so this is enough to exercise the OpenHTF plan/phase machinery
    with zero real HTTP.
    """

    run: dict
    steps: list
    # step_id -> queue of result payloads; each dispatch_next_step() call
    # pops the next queued result for whichever step still has one queued,
    # simulating the device eventually finishing and the backend recording it.
    results_by_step: dict = field(default_factory=dict)
    dispatch_calls: list = field(default_factory=list)
    begin_step_calls: list = field(default_factory=list)
    submit_result_calls: list = field(default_factory=list)
    cancel_calls: list = field(default_factory=list)

    def get_test_run(self, run_id: str) -> dict:
        results = []
        for step_id, queue in self.results_by_step.items():
            if queue and queue[0].get("_delivered"):
                results.append({**queue[0], "step": step_id})
        return {**self.run, "results": results}

    def get_profile_version_steps(self, version_id: str) -> list:
        return self.steps

    def dispatch_next_step(self, run_id: str):
        self.dispatch_calls.append(run_id)
        for step_id, queue in self.results_by_step.items():
            if queue and not queue[0].get("_delivered"):
                queue[0]["_delivered"] = True
                break
        return None

    def cancel_test_run(self, run_id: str, reason: str = ""):
        self.cancel_calls.append(run_id)
        return {"status": "CANCELLED"}

    def begin_step(self, run_id: str, step_id: str) -> dict:
        self.begin_step_calls.append((run_id, step_id))
        return {"test_result_id": f"result-{step_id}"}

    def submit_result(self, run_id: str, result_id: str, **kwargs) -> dict:
        self.submit_result_calls.append({"run_id": run_id, "result_id": result_id, **kwargs})
        return {"ok": True}


class FakeBleDevice:
    """Fake for the BLE calls station_agent.openhtf.plugs.BleStationPlug wraps."""

    def __init__(
        self, *, connect_result=None, authorize_result=None, wifi_networks=None,
        configure_result=None, raise_on: str | None = None, error_code: str = "BLE_CONNECTION_FAILED",
    ):
        self._connect_result = connect_result or {"device_uid": "QBOX-TEST"}
        self._authorize_result = authorize_result or {"secure_session_id": "sess-1"}
        self._wifi_networks = wifi_networks if wifi_networks is not None else [{"ssid": "Network1"}]
        self._configure_result = configure_result or "CONNECTED"
        self._raise_on = raise_on
        self._error_code = error_code

    def _maybe_raise(self, call: str):
        if self._raise_on == call:
            raise StationBleError(self._error_code, f"{call} failed")

    async def connect(self, timeout: float = 20.0):
        self._maybe_raise("connect")
        return self._connect_result

    async def authorize(self, *, session_id: str, token: str, expires_at: str):
        self._maybe_raise("authorize")
        return self._authorize_result

    async def scan_wifi(self):
        self._maybe_raise("scan_wifi")
        return self._wifi_networks

    async def configure_wifi(self, *, ssid: str, password: str):
        self._maybe_raise("configure_wifi")
        return self._configure_result

    async def disconnect(self):
        pass


@pytest.fixture
def sample_step():
    def _make(step_type: str, **overrides) -> dict:
        base = {
            "id": f"step-{step_type.lower()}",
            "step_type": step_type,
            "order": overrides.pop("order", 1),
            "timeout_seconds": 5,
            "failure_policy": "MARK_FAILED_CONTINUE",
        }
        base.update(overrides)
        return base

    return _make
