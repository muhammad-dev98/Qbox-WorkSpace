from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import WSMsgType, web

from .ble_client import DiscoveredDevice, QBoxBleDevice, StationBleError, discover_qbox_devices
from .local_auth import LocalAuthError, OperatorAuthenticator
from .openhtf.backend_client import BackendClient, BackendError
from .openhtf.config import StationCredentials
from .openhtf.runner import PauseRejectedError, StationBusyError, StationTestRunner

logger = logging.getLogger(__name__)

STATION_VERSION = "0.1.0"


def _error_response(code: str, message: str, *, status: int = 400) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


@dataclass
class DeviceSession:
    device: QBoxBleDevice
    owner_session_id: str


@dataclass
class StationState:
    station_id: str
    started_at: float = field(default_factory=time.time)
    sessions: dict[str, DeviceSession] = field(default_factory=dict)
    ws_clients: set[web.WebSocketResponse] = field(default_factory=set)

    async def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"event": event, "payload": payload, "ts": time.time()})
        dead = set()
        for ws in self.ws_clients:
            try:
                await ws.send_str(message)
            except Exception:
                dead.add(ws)
        self.ws_clients -= dead


def _device_id_for(address: str) -> str:
    # Stable, non-sensitive id derived from the BLE address - the React app
    # never needs to know or handle a raw MAC address directly.
    return address.replace(":", "").lower()


@web.middleware
async def _cors_middleware(request: web.Request, handler):
    # The Factory Panel runs on http://localhost:5173 (or a production
    # origin) - a different origin from this station agent's
    # http://127.0.0.1:<port>, so the browser enforces CORS on every
    # request. Only ever bound to loopback (see run()'s host default), so
    # allowing any origin here does not expose this to the network - a
    # remote page still cannot reach 127.0.0.1 on the technician's own
    # machine from outside it.
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    """
    Requires a valid operator JWT (Authorization: Bearer <token>, checked
    against the backend's own /auth/profile - see local_auth.py) on every
    route. `app["authenticator"]` is None only in tests that construct
    build_app() without backend credentials; production always has one set
    by on_startup before any real request can arrive - the local HTTP API
    previously had no auth at all beyond loopback binding, which is no
    longer sufficient once this process also holds a station-wide backend
    credential reachable indirectly through it. Read from the app at
    request time (not closed over at app-construction time) because the
    authenticator's aiohttp.ClientSession must be created inside the
    running event loop, i.e. in on_startup, after build_app() returns.
    """
    if request.method == "OPTIONS":
        return await handler(request)
    authenticator: OperatorAuthenticator | None = request.app.get("authenticator")
    if authenticator is None:
        return await handler(request)
    try:
        principal = await authenticator.authenticate(request)
    except LocalAuthError as exc:
        status = 401 if exc.code != "LOCAL_AUTH_FORBIDDEN" else 403
        return _error_response(exc.code, str(exc), status=status)
    request["operator"] = principal
    return await handler(request)


def build_app(
    *,
    station_id: str,
    credentials: StationCredentials | None = None,
    runner: StationTestRunner | None = None,
) -> web.Application:
    state = StationState(station_id=station_id)
    app = web.Application(middlewares=[_cors_middleware, _auth_middleware])
    app["state"] = state
    app["address_by_id"] = {}
    app["ble_device_by_id"] = {}
    app["credentials"] = credentials
    app["runner"] = runner  # constructed in on_startup once the event loop is running, unless injected (tests)
    app["authenticator"] = None  # set in on_startup once credentials are known, unless injected via app (tests)

    async def _on_startup(app: web.Application) -> None:
        if credentials is not None:
            session = aiohttp.ClientSession()
            app["http_session"] = session
            if app["authenticator"] is None:
                app["authenticator"] = OperatorAuthenticator(backend_url=credentials.backend_url, session=session)
            if app["runner"] is None:
                app["runner"] = StationTestRunner(
                    credentials=credentials, main_loop=asyncio.get_running_loop(), broadcast=state.broadcast
                )

    async def _on_cleanup(app: web.Application) -> None:
        runner_instance: StationTestRunner | None = app.get("runner")
        if runner_instance is not None:
            runner_instance.shutdown()
        session: aiohttp.ClientSession | None = app.get("http_session")
        if session is not None:
            await session.close()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    async def get_status(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "station_id": state.station_id,
                "version": STATION_VERSION,
                "uptime_seconds": time.time() - state.started_at,
                "connected_devices": [
                    {"device_id": did, "device_uid": s.device.device_uid, "connected": s.device.connected}
                    for did, s in state.sessions.items()
                ],
            }
        )

    async def discover(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        timeout = float(body.get("timeout_seconds", 8.0))
        name_prefix = str(body.get("name_prefix", "QBox"))
        try:
            devices: list[DiscoveredDevice] = await discover_qbox_devices(name_prefix=name_prefix, timeout=timeout)
        except Exception as exc:
            logger.exception("station_discover_failed")
            return _error_response("BLE_ADAPTER_NOT_FOUND", str(exc), status=503)
        result = []
        for d in devices:
            device_id = _device_id_for(d.address)
            app["address_by_id"][device_id] = d.address
            app["ble_device_by_id"][device_id] = d.ble_device
            result.append({"device_id": device_id, **d.as_dict()})
            await state.broadcast("device.discovered", {"device_id": device_id, **d.as_dict()})
        return web.json_response({"devices": result})

    async def connect_device(request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        address = app["address_by_id"].get(device_id)
        if not address:
            return _error_response("BLE_DEVICE_NOT_FOUND", "Run discovery first", status=404)
        body = await request.json() if request.can_read_body else {}
        expected_device_uid = body.get("expected_device_uid")

        def on_event(event: str, payload: dict[str, Any]) -> None:
            asyncio.create_task(state.broadcast(event, {"device_id": device_id, **payload}))

        device = QBoxBleDevice(
            address=address,
            ble_device=app["ble_device_by_id"].get(device_id),
            expected_device_uid=expected_device_uid,
            on_event=on_event,
        )
        try:
            identity = await device.connect()
        except StationBleError as exc:
            logger.warning("station_ble_connect_rejected device_id=%s code=%s message=%s", device_id, exc.code, str(exc))
            return _error_response(exc.code, str(exc), status=409)
        state.sessions[device_id] = DeviceSession(device=device, owner_session_id=str(uuid.uuid4()))
        return web.json_response({"device_id": device_id, **identity})

    async def disconnect_device(request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        session = state.sessions.pop(device_id, None)
        if session:
            await session.device.disconnect()
        return web.json_response({"device_id": device_id, "disconnected": True})

    def _require_session(device_id: str) -> DeviceSession | None:
        return state.sessions.get(device_id)

    async def authorize_device(request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        session = _require_session(device_id)
        if not session:
            return _error_response("BLE_DEVICE_NOT_FOUND", "Device is not connected", status=404)
        body = await request.json()
        missing = [key for key in ("session_id", "token", "expires_at") if key not in body]
        if missing:
            return _error_response(
                "BLE_AUTHORIZE_REQUEST_INVALID",
                f"Missing required field(s): {', '.join(missing)}. The Panel must obtain a backend-issued BLE session token before calling authorize.",
                status=400,
            )
        try:
            result = await session.device.authorize(
                session_id=body["session_id"], token=body["token"], expires_at=body["expires_at"]
            )
        except StationBleError as exc:
            return _error_response(exc.code, str(exc), status=401)
        return web.json_response({"device_id": device_id, "authorized": True, "secure_session_id": result.get("secure_session_id")})

    async def wifi_scan(request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        session = _require_session(device_id)
        if not session:
            return _error_response("BLE_DEVICE_NOT_FOUND", "Device is not connected", status=404)
        await state.broadcast("wifi.scan.started", {"device_id": device_id})
        try:
            networks = await session.device.scan_wifi()
        except StationBleError as exc:
            await state.broadcast("wifi.failed", {"device_id": device_id, "code": exc.code, "message": str(exc)})
            return _error_response(exc.code, str(exc), status=502)
        await state.broadcast("wifi.scan.result", {"device_id": device_id, "networks": networks})
        return web.json_response({"device_id": device_id, "networks": networks})

    async def wifi_connect(request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        session = _require_session(device_id)
        if not session:
            return _error_response("BLE_DEVICE_NOT_FOUND", "Device is not connected", status=404)
        body = await request.json()
        ssid = str(body.get("ssid") or "")
        password = str(body.get("password") or "")
        if not ssid:
            return _error_response("WIFI_NETWORK_NOT_FOUND", "ssid is required")
        await state.broadcast("wifi.connecting", {"device_id": device_id, "ssid": ssid})
        try:
            status = await session.device.configure_wifi(ssid=ssid, password=password)
        except StationBleError as exc:
            await state.broadcast("wifi.failed", {"device_id": device_id, "code": exc.code, "message": str(exc)})
            return _error_response(exc.code, str(exc), status=502)
        finally:
            password = ""  # never retained past this call
        await state.broadcast("wifi.connected", {"device_id": device_id, "status": status})
        return web.json_response({"device_id": device_id, "status": status})

    def _runner_or_503(request: web.Request) -> StationTestRunner | None:
        runner_instance: StationTestRunner | None = request.app.get("runner")
        return runner_instance

    async def start_test_run(request: web.Request) -> web.Response:
        runner_instance = _runner_or_503(request)
        if runner_instance is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        run_id = request.match_info["run_id"]
        body = await request.json() if request.can_read_body else {}
        ble_context = body.get("ble_context") or {}
        try:
            runner_instance.start_run(run_id, ble_context=ble_context)
        except StationBusyError as exc:
            return _error_response("STATION_BUSY", str(exc), status=409)
        return web.json_response({"run_id": run_id, "status": "STARTED"}, status=202)

    async def test_run_status(request: web.Request) -> web.Response:
        runner_instance = _runner_or_503(request)
        if runner_instance is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        return web.json_response(runner_instance.get_status(request.match_info["run_id"]))

    async def abort_test_run(request: web.Request) -> web.Response:
        runner_instance = _runner_or_503(request)
        if runner_instance is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        runner_instance.abort(request.match_info["run_id"])
        return web.json_response({"run_id": request.match_info["run_id"], "aborted": True})

    async def pause_test_run(request: web.Request) -> web.Response:
        runner_instance = _runner_or_503(request)
        if runner_instance is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        try:
            runner_instance.request_pause(request.match_info["run_id"])
        except PauseRejectedError as exc:
            return _error_response("PAUSE_NOT_SAFE", str(exc), status=409)
        return web.json_response({"run_id": request.match_info["run_id"], "pause_requested": True})

    async def resume_test_run(request: web.Request) -> web.Response:
        runner_instance = _runner_or_503(request)
        if runner_instance is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        runner_instance.resume(request.match_info["run_id"])
        return web.json_response({"run_id": request.match_info["run_id"], "resumed": True})

    def _backend_client_or_none() -> "BackendClient | None":
        # Same StationCredentials (X-Station-Key) the OpenHTF flow's
        # BackendClientPlug already uses - a fresh, cheap client instance,
        # not a second credential/trust boundary. Lets the browser-driven
        # manual BLE flow (BleProvisioningCard, same physical bleak/BlueZ
        # session as the automatic flow) record its real outcome against
        # the TestRun the same way the automatic flow does - the operator's
        # JWT (already required by _auth_middleware for every route in this
        # file) authorizes them to ask THIS station to do it, not to talk
        # to the backend directly as the station themselves.
        if credentials is None:
            return None
        return BackendClient(credentials)

    async def begin_manual_step(request: web.Request) -> web.Response:
        client = _backend_client_or_none()
        if client is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        run_id, step_id = request.match_info["run_id"], request.match_info["step_id"]
        try:
            result = await asyncio.get_running_loop().run_in_executor(None, client.begin_step, run_id, step_id)
        except BackendError as exc:
            return _error_response(exc.code, exc.message, status=exc.status_code or 502)
        return web.json_response(result)

    async def submit_manual_step_result(request: web.Request) -> web.Response:
        client = _backend_client_or_none()
        if client is None:
            return _error_response("STATION_NOT_CONFIGURED", "Station has no backend credentials configured", status=503)
        run_id, result_id = request.match_info["run_id"], request.match_info["result_id"]
        body = await request.json()
        missing = [key for key in ("status", "evidence_type") if key not in body]
        if missing:
            return _error_response("SUBMIT_RESULT_INVALID", f"Missing required field(s): {', '.join(missing)}", status=400)
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: client.submit_result(
                    run_id, result_id,
                    status=body["status"],
                    evidence_type=body["evidence_type"],
                    actual_values=body.get("actual_values"),
                    error_code=body.get("error_code", ""),
                ),
            )
        except BackendError as exc:
            return _error_response(exc.code, exc.message, status=exc.status_code or 502)
        return web.json_response(result)

    async def events_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        state.ws_clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            state.ws_clients.discard(ws)
        return ws

    app.router.add_get("/station/status", get_status)
    app.router.add_post("/devices/discover", discover)
    app.router.add_post("/devices/{device_id}/connect", connect_device)
    app.router.add_post("/devices/{device_id}/disconnect", disconnect_device)
    app.router.add_post("/devices/{device_id}/authorize", authorize_device)
    app.router.add_post("/devices/{device_id}/wifi/scan", wifi_scan)
    app.router.add_post("/devices/{device_id}/wifi/connect", wifi_connect)
    app.router.add_get("/events", events_ws)
    app.router.add_post("/test-runs/{run_id}/start", start_test_run)
    app.router.add_get("/test-runs/{run_id}/status", test_run_status)
    app.router.add_post("/test-runs/{run_id}/abort", abort_test_run)
    app.router.add_post("/test-runs/{run_id}/pause", pause_test_run)
    app.router.add_post("/test-runs/{run_id}/resume", resume_test_run)
    app.router.add_post("/test-runs/{run_id}/steps/{step_id}/begin", begin_manual_step)
    app.router.add_post("/test-runs/{run_id}/results/{result_id}/submit", submit_manual_step_result)
    return app


def run(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    station_id: str = "FACTORY-STATION-001",
    credentials: StationCredentials | None = None,
) -> None:
    app = build_app(station_id=station_id, credentials=credentials)
    web.run_app(app, host=host, port=port, print=None)
