from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import openhtf as htf
from openhtf.output.callbacks import json_factory

from . import plan_builder
from .backend_client import BackendClient, BackendError
from .config import StationCredentials
from .phases import UNSAFE_TO_PAUSE_STEP_TYPES
from .plugs import BackendClientPlug, BleStationPlug

logger = logging.getLogger(__name__)

RECORDS_DIR = Path.home() / ".local" / "share" / "qbox-factory-station" / "openhtf-records"


class StationBusyError(Exception):
    """Raised when a second run is requested while one is already active - one physical fixture, one run at a time."""


class PauseRejectedError(Exception):
    """Raised when a pause is requested while the currently-executing phase is not safe to pause."""


@dataclass
class RunState:
    run_id: str
    status: str = "RUNNING"  # RUNNING | PAUSED | DONE | ERROR | ABORTED
    current_step_type: str | None = None
    pause_requested: bool = False
    result: bool | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None


class StationTestRunner:
    """
    Owns the OpenHTF execution lifecycle for this Station process. Two
    background execution contexts, in addition to the main aiohttp loop
    server.py already runs for the Panel-facing HTTP/WS server:

    1. A dedicated BLE asyncio event loop + thread - owns every
       QBoxBleDevice/BleakClient instance (bleak is loop-bound), shared by
       BleStationPlug for OpenHTF-driven BLE phases. The existing
       /devices/* endpoints in server.py are left exactly as they are in
       this phase (using the main aiohttp loop) - only new OpenHTF-driven
       BLE calls route through this dedicated loop, to minimize risk to the
       already-verified BLE path.
    2. A single-worker ThreadPoolExecutor running the blocking
       openhtf.Test.execute() call - one active run per station, matching
       "one physical fixture" reality (an explicit scope limit, not an
       oversight).

    OpenHTF's own bundled web/Station-API server is never constructed here
    (see openhtf.output.servers.station_server) - it is opt-in, not
    started implicitly by Test.execute(), so simply never using it is
    sufficient to avoid a second, redundant local HTTP surface.
    """

    def __init__(self, *, credentials: StationCredentials, main_loop: asyncio.AbstractEventLoop, broadcast: Callable[[str, dict], Any]):
        self._credentials = credentials
        self._main_loop = main_loop
        self._broadcast = broadcast  # StationState.broadcast(event, payload) coroutine function
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openhtf-run")
        self._active: RunState | None = None
        self._lock = threading.Lock()

        self._ble_loop = asyncio.new_event_loop()
        self._ble_thread = threading.Thread(target=self._ble_loop.run_forever, name="station-ble-loop", daemon=True)
        self._ble_thread.start()

        BackendClientPlug.credentials = credentials
        BleStationPlug.loop = self._ble_loop

        RECORDS_DIR.mkdir(parents=True, exist_ok=True)

    def get_status(self, run_id: str) -> dict:
        with self._lock:
            state = self._active
        if state is None or state.run_id != run_id:
            return {"run_id": run_id, "station_status": "IDLE"}
        return {
            "run_id": state.run_id,
            "phase": state.current_step_type,
            "station_status": state.status,
            "result": state.result,
            "error": state.error,
        }

    def start_run(self, run_id: str, *, ble_context: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._active is not None and self._active.status in {"RUNNING", "PAUSED"}:
                raise StationBusyError(f"Station is already running test-run {self._active.run_id}")
            state = RunState(run_id=run_id)
            self._active = state
        self._executor.submit(self._execute, state, ble_context or {})

    def abort(self, run_id: str) -> None:
        with self._lock:
            state = self._active
            if state is None or state.run_id != run_id:
                return
            state.pause_requested = False
        backend = BackendClient(self._credentials)
        try:
            backend.cancel_test_run(run_id, reason="aborted from station")
        except BackendError:
            logger.exception("station_abort_backend_notify_failed run_id=%s", run_id)
        # Best-effort: an in-flight actuation phase finishes its current
        # physical operation to a safe state (BleStationPlug.tearDown /
        # the dispatched phase's own poll loop noticing CANCELLED) before
        # this is fully honored - abort requests a stop, it does not yank
        # power out from under a live phase.

    def request_pause(self, run_id: str) -> None:
        with self._lock:
            state = self._active
            if state is None or state.run_id != run_id or state.status != "RUNNING":
                return
            if state.current_step_type in UNSAFE_TO_PAUSE_STEP_TYPES:
                raise PauseRejectedError(f"{state.current_step_type} is not safe to pause")
            state.pause_requested = True

    def resume(self, run_id: str) -> None:
        with self._lock:
            state = self._active
            if state is None or state.run_id != run_id:
                return
            state.pause_requested = False
            if state.status == "PAUSED":
                state.status = "RUNNING"

    # -- internal --

    def _on_phase_event(self, state: RunState, event_type: str, step_type: str, payload: dict) -> None:
        if event_type == "phase.started":
            state.current_step_type = step_type
        self._emit(event_type, {"run_id": state.run_id, "step_type": step_type, **payload})

        # Cooperative pause: honored only between phases (see
        # request_pause()'s safe_to_pause check for why it's rejected
        # outright during an unsafe phase rather than merely deferred past
        # it - an unsafe phase never even sets pause_requested=True).
        if event_type == "phase.completed" and state.pause_requested:
            state.status = "PAUSED"
            self._emit("run.paused", {"run_id": state.run_id})
            while state.pause_requested and state.status == "PAUSED":
                time.sleep(0.5)
            if state.status == "PAUSED":
                state.status = "RUNNING"

    def _emit(self, event: str, payload: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(event, payload), self._main_loop)
        except Exception:
            logger.exception("station_event_broadcast_failed event=%s", event)

    def _execute(self, state: RunState, ble_context: dict[str, Any]) -> None:
        backend = BackendClient(self._credentials)
        try:
            phases = plan_builder.build_plan(
                state.run_id, backend, ble_context=ble_context,
                on_event=lambda et, st, pl: self._on_phase_event(state, et, st, pl),
            )
        except Exception as exc:
            logger.exception("station_plan_build_failed run_id=%s", state.run_id)
            state.status = "ERROR"
            state.error = str(exc)
            state.finished_at = time.time()
            self._emit("run.error", {"run_id": state.run_id, "error": str(exc)})
            return

        test = htf.Test(*phases, test_name=f"qbox-{state.run_id}")
        record_path = str(RECORDS_DIR / f"{state.run_id}.json")
        test.add_output_callbacks(json_factory.OutputToJSON(record_path, indent=2))

        try:
            result = test.execute(test_start=lambda: state.run_id)
        except Exception as exc:
            logger.exception("station_test_execute_failed run_id=%s", state.run_id)
            state.status = "ERROR"
            state.error = str(exc)
            result = False
        else:
            state.status = "DONE"

        state.result = result
        state.finished_at = time.time()
        self._emit("run.completed", {"run_id": state.run_id, "result": result, "status": state.status})

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)
