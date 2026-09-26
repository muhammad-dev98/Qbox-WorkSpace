from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from .crypto import ClientSecureSession, new_request_id
from .protocol import BLEReassembler, chunk_message

logger = logging.getLogger(__name__)

# Real GATT UUIDs from Qbox-Hardware platform/qbox_platform/bluetooth/gatt_server.py.
# This station agent is a native BLE client for the SAME existing device
# protocol and characteristics - it does not define a new GATT contract on
# the device side. Reusing the existing, already-hardened contract instead
# of inventing a second one.
QBOX_BLE_SERVICE_UUID = "7c6b5000-5162-6f78-2d42-4c452d563100"
QBOX_IDENTIFY_UUID = "7c6b5001-5162-6f78-2d42-4c452d563100"
QBOX_RX_UUID = "7c6b5002-5162-6f78-2d42-4c452d563100"
QBOX_TX_UUID = "7c6b5003-5162-6f78-2d42-4c452d563100"


class StationBleError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


@dataclass
class DiscoveredDevice:
    address: str
    name: str
    rssi: int | None
    # Keep the scanner's BLEDevice object, not only its MAC address. BlueZ
    # uses the object to retain the LE address/type and GATT transport. If
    # BleakClient is given only a string, BlueZ may try a BR/EDR profile and
    # return org.bluez.Error.NotAvailable/
    # br-connection-profile-unavailable for a GATT-only QBox device.
    ble_device: BLEDevice | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {"address": self.address, "name": self.name, "rssi": self.rssi}


@dataclass
class QBoxBleDevice:
    address: str
    ble_device: BLEDevice | None = None
    expected_device_uid: str | None = None
    on_event: Callable[[str, dict[str, Any]], None] | None = None

    _client: BleakClient | None = field(default=None, init=False, repr=False)
    _reassembler: BLEReassembler = field(default_factory=BLEReassembler, init=False, repr=False)
    _pending: asyncio.Future | None = field(default=None, init=False, repr=False)
    _session: ClientSecureSession | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    device_uid: str | None = field(default=None, init=False)
    capabilities: list[str] = field(default_factory=list, init=False)

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event:
            try:
                self.on_event(event, payload)
            except Exception:
                logger.exception("station_ble_event_handler_failed event=%s", event)

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    @property
    def authorized(self) -> bool:
        return self._session is not None

    async def connect(self, *, timeout: float = 20.0) -> dict[str, Any]:
        last_error: Exception | None = None
        require_fresh_device = False
        # BlueZ can retain a stale BR/EDR profile attempt after a previous
        # connection. Retry once after explicitly disconnecting so a transient
        # br-connection-profile-unavailable does not strand the BLE workflow.
        for attempt in range(3):
            # Prefer the object returned by BleakScanner so the Linux BlueZ
            # backend preserves LE address type and avoids BR/EDR profile
            # auto-connect. Fall back to the address for callers that supply
            # one directly (for example older API clients/tests).
            target = self.ble_device or self.address
            # Discovery and connect are separate HTTP operations. Refresh the
            # BlueZ device object immediately before connecting so a cached
            # object from the scan cannot carry a stale address type/path
            # after the advertiser rotated or a prior connection closed.
            try:
                refreshed = await BleakScanner.find_device_by_address(self.address, timeout=min(timeout, 8.0))
                if refreshed is not None:
                    target = refreshed
                    self.ble_device = refreshed
                elif require_fresh_device:
                    # After removing a stale BlueZ Device1 object, never pass
                    # the old BLEDevice/address back to Bleak. Wait for the
                    # advertiser to reappear and let the next attempt scan
                    # again instead of recreating the same BR/EDR error.
                    logger.info("station_ble_waiting_for_fresh_advertisement address=%s", self.address)
                    await asyncio.sleep(1.0)
                    continue
            except Exception:
                logger.debug("station_ble_refresh_before_connect_failed", exc_info=True)
            self._client = BleakClient(target, disconnected_callback=self._on_disconnect, timeout=timeout)
            try:
                await self._client.connect()
                break
            except Exception as exc:
                last_error = exc
                # Always close the Bleak client before touching BlueZ's
                # Device1 object. Removing/powering down first races the
                # in-flight Connect() and produces bluetoothd's
                # "No matching connection for device" error.
                try:
                    await asyncio.wait_for(self._client.disconnect(), timeout=3.0)
                except Exception:
                    pass
                if "br-connection-profile-unavailable" in str(exc):
                    # BlueZ can retain a stale BR/EDR Device1 object for a
                    # QBox address after an earlier failed pairing attempt.
                    # Remove only this already-discovered QBox entry, then
                    # let the next attempt resolve a fresh LE/GATT path.
                    await self._remove_stale_bluez_device()
                    self.ble_device = None
                    require_fresh_device = True
                    if attempt == 0:
                        await self._reset_bluez_adapter()
                logger.warning(
                    "station_ble_connect_attempt_failed address=%s attempt=%s error=%s",
                    self.address,
                    attempt + 1,
                    repr(exc),
                )
                if attempt < 2:
                    await asyncio.sleep(0.5)
        else:
            detail = str(last_error)
            logger.error("station_ble_connect_failed address=%s error=%r", self.address, last_error)
            if "br-connection-profile-unavailable" in detail:
                raise StationBleError(
                    "BLE_GATT_CONNECTION_UNAVAILABLE",
                    "The QBox BLE GATT service is temporarily unavailable. Rediscover the device and try again.",
                ) from last_error
            raise StationBleError("BLE_CONNECTION_FAILED", detail) from last_error

        services = self._client.services
        if not any(s.uuid.lower() == QBOX_BLE_SERVICE_UUID for s in services):
            await self.disconnect()
            raise StationBleError("BLE_GATT_SERVICE_NOT_FOUND", "QBox provisioning service not found on this device")

        try:
            await self._client.start_notify(QBOX_TX_UUID, self._on_notify)
        except Exception as exc:
            await self.disconnect()
            raise StationBleError("BLE_CHARACTERISTIC_NOT_FOUND", str(exc)) from exc

        identify_bytes = await self._client.read_gatt_char(QBOX_IDENTIFY_UUID)
        identify = json.loads(identify_bytes.decode("utf-8"))
        self.device_uid = identify.get("device_uid")
        self.capabilities = identify.get("capabilities") or []

        if self.expected_device_uid and self.device_uid != self.expected_device_uid:
            await self.disconnect()
            raise StationBleError(
                "BLE_DEVICE_IDENTITY_MISMATCH",
                f"Connected to {self.device_uid}, not the expected device {self.expected_device_uid}",
            )

        self._emit("device.connected", {"address": self.address, "device_uid": self.device_uid})
        return {"device_uid": self.device_uid, "capabilities": self.capabilities}

    async def _remove_stale_bluez_device(self) -> None:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["bluetoothctl", "remove", self.address],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            logger.info(
                "station_ble_stale_bluez_entry_removed address=%s returncode=%s",
                self.address,
                result.returncode,
            )
        except Exception:
            logger.debug("station_ble_stale_bluez_remove_failed address=%s", self.address, exc_info=True)

    async def _reset_bluez_adapter(self) -> None:
        """Recover a BlueZ controller stuck with a stale BR/EDR profile.

        This is deliberately used only after the QBox-specific profile error
        and only for the local adapter. It does not alter controller mode or
        pairings; it briefly powers the adapter down/up so BlueZ rebuilds its
        LE Device1 objects before the next scan.
        """
        try:
            for action in ("off", "on"):
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["bluetoothctl", "power", action],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                logger.info("station_ble_adapter_power_%s returncode=%s", action, result.returncode)
                if action == "off":
                    await asyncio.sleep(0.75)
        except Exception:
            logger.debug("station_ble_adapter_reset_failed", exc_info=True)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            # BlueZ can leave Device1.Disconnect pending after a failed LE
            # profile negotiation. Never let station shutdown block the
            # systemd stop timeout or strand the next discovery session.
            try:
                await asyncio.wait_for(self._client.disconnect(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("station_ble_disconnect_timeout address=%s", self.address)
            except Exception:
                logger.debug("station_ble_disconnect_failed address=%s", self.address, exc_info=True)
        self._session = None

    def _on_disconnect(self, _client: BleakClient) -> None:
        self._session = None
        self._emit("device.disconnected", {"address": self.address, "device_uid": self.device_uid})

    def _on_notify(self, _handle: int, data: bytearray) -> None:
        try:
            chunk = json.loads(bytes(data).decode("utf-8"))
            full = self._reassembler.add(chunk)
        except Exception as exc:
            if self._pending and not self._pending.done():
                self._pending.set_exception(exc)
            return
        if full is None:
            return
        if self._pending and not self._pending.done():
            self._pending.set_result(full)

    async def _request_raw(self, plaintext_payload: dict[str, Any], *, timeout: float = 15.0) -> bytes:
        if not self._client or not self._client.is_connected:
            raise StationBleError("BLE_GATT_DISCONNECTED", "Not connected to device")
        async with self._lock:
            loop = asyncio.get_running_loop()
            self._pending = loop.create_future()
            body = json.dumps(plaintext_payload).encode("utf-8")
            for wire_chunk in chunk_message(body):
                await self._client.write_gatt_char(QBOX_RX_UUID, json.dumps(wire_chunk).encode("utf-8"), response=False)
            try:
                return await asyncio.wait_for(self._pending, timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise StationBleError("BLE_RESPONSE_TIMEOUT", "Timed out waiting for a response from the device") from exc
            finally:
                self._pending = None

    async def authorize(self, *, session_id: str, token: str, expires_at: str) -> dict[str, Any]:
        response_bytes = await self._request_raw({"action": "authorize", "session_id": session_id, "token": token, "expires_at": expires_at})
        response = json.loads(response_bytes.decode("utf-8"))
        if not response.get("authorized") or not response.get("secure_session_id"):
            raise StationBleError("BLE_AUTH_FAILED", response.get("error") or response.get("message") or "Device rejected the provisioning token")
        self._session = ClientSecureSession.from_authorize_response(
            secure_session_id=response["secure_session_id"], token=token, session_id=session_id, expires_at=expires_at
        )
        return response

    async def _encrypted_request(self, action: dict[str, Any]) -> dict[str, Any]:
        if not self._session:
            raise StationBleError("BLE_SESSION_EXPIRED", "BLE session is not authorized yet")
        frame = self._session.encrypt(json.dumps(action).encode("utf-8"))
        response_bytes = await self._request_raw(frame)
        response_frame = json.loads(response_bytes.decode("utf-8"))
        plaintext = self._session.decrypt(response_frame)
        result = json.loads(plaintext.decode("utf-8"))
        if isinstance(result, dict) and "error" in result:
            raise StationBleError("WIFI_REQUEST_FAILED", str(result["error"]))
        return result

    async def scan_wifi(self) -> list[dict[str, Any]]:
        result = await self._encrypted_request({"action": "wifi.scan"})
        return result.get("networks") or []

    async def configure_wifi(self, *, ssid: str, password: str) -> dict[str, Any]:
        result = await self._encrypted_request({"action": "wifi.configure", "ssid": ssid, "password": password})
        return result.get("status") or {}


async def discover_qbox_devices(*, name_prefix: str = "QBox", timeout: float = 8.0) -> list[DiscoveredDevice]:
    found: dict[str, DiscoveredDevice] = {}

    def _callback(device: BLEDevice, advertisement_data) -> None:
        name = device.name or advertisement_data.local_name or ""
        service_uuids = [u.lower() for u in (advertisement_data.service_uuids or [])]
        if not name.startswith(name_prefix) and QBOX_BLE_SERVICE_UUID not in service_uuids:
            return
        found[device.address] = DiscoveredDevice(
            address=device.address,
            name=name,
            rssi=getattr(advertisement_data, "rssi", None),
            ble_device=device,
        )

    scanner = BleakScanner(detection_callback=_callback)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()
    return list(found.values())
