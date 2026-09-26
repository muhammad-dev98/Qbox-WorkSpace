from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from openhtf import plugs

from ..ble_client import QBoxBleDevice, StationBleError
from .backend_client import BackendClient
from .config import StationCredentials


class BackendClientPlug(plugs.BasePlug):
    """
    Thin holder for a BackendClient instance so OpenHTF phases can reach the
    backend without each phase constructing its own client/session.

    OpenHTF's PlugManager always constructs plugs with zero args, so
    per-run configuration (which backend, which station credentials) is
    passed via a class attribute set immediately before `Test.execute()`
    (StationTestRunner.configure(), see runner.py) - the standard pattern
    for configurable OpenHTF plugs. Safe here because the runner only ever
    runs one Test at a time per station (one active run per station is an
    explicit, enforced design limit - a real factory fixture is one
    physical station), so there is no concurrent execute() call that could
    race on this class attribute.
    """

    credentials: StationCredentials | None = None

    def __init__(self):
        if type(self).credentials is None:
            raise RuntimeError("BackendClientPlug.credentials not configured before Test.execute()")
        self.client = BackendClient(type(self).credentials)


class BleStationPlug(plugs.BasePlug):
    """
    Bridges OpenHTF's synchronous phase execution (a plain worker thread -
    see runner.py) into the Station's existing, unmodified asyncio BLE
    stack (station_agent.ble_client, bleak/BlueZ) by running each BLE
    coroutine on a dedicated BLE event loop via run_coroutine_threadsafe.
    Never touches ble_client.py itself - every method here is a synchronous
    wrapper around exactly the calls the existing /devices/* HTTP handlers
    in server.py already make.
    """

    loop: asyncio.AbstractEventLoop | None = None  # set via configure() before Test.execute(), see BackendClientPlug's docstring

    def __init__(self):
        self._loop = type(self).loop
        self._device: QBoxBleDevice | None = None

    def _run(self, coro, *, timeout: float) -> Any:
        if self._loop is None:
            raise StationBleError("BLE_ADAPTER_NOT_FOUND", "BLE event loop not started")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise StationBleError("BLE_CONNECTION_FAILED", "BLE operation timed out") from exc

    def connect(self, address: str, *, expected_device_uid: str | None = None, timeout: float = 20.0) -> dict:
        self._device = QBoxBleDevice(address=address, expected_device_uid=expected_device_uid)
        return self._run(self._device.connect(timeout=timeout), timeout=timeout + 5)

    def authorize(self, *, session_id: str, token: str, expires_at: str, timeout: float = 15.0) -> dict:
        if self._device is None:
            raise StationBleError("BLE_DEVICE_NOT_FOUND", "connect() must be called before authorize()")
        return self._run(
            self._device.authorize(session_id=session_id, token=token, expires_at=expires_at), timeout=timeout
        )

    def scan_wifi(self, *, timeout: float = 20.0) -> list[dict]:
        if self._device is None:
            raise StationBleError("BLE_DEVICE_NOT_FOUND", "connect()/authorize() must be called before scan_wifi()")
        return self._run(self._device.scan_wifi(), timeout=timeout)

    def configure_wifi(self, *, ssid: str, password: str, timeout: float = 30.0) -> dict:
        if self._device is None:
            raise StationBleError("BLE_DEVICE_NOT_FOUND", "connect()/authorize() must be called before configure_wifi()")
        try:
            return self._run(self._device.configure_wifi(ssid=ssid, password=password), timeout=timeout)
        finally:
            password = ""  # never retained past this call, matching server.py's existing wifi_connect handler

    def disconnect(self, *, timeout: float = 10.0) -> None:
        if self._device is None:
            return
        try:
            self._run(self._device.disconnect(), timeout=timeout)
        finally:
            self._device = None

    def tearDown(self) -> None:
        if self._device is not None and self._loop is not None:
            try:
                self._run(self._device.disconnect(), timeout=5)
            except StationBleError:
                pass
            self._device = None
