from __future__ import annotations

import asyncio
import time

import openhtf as htf
import pytest

from station_agent.openhtf import runner as runner_module
from station_agent.openhtf.config import StationCredentials
from station_agent.openhtf.runner import PauseRejectedError, StationBusyError, StationTestRunner


@pytest.fixture
def credentials():
    return StationCredentials(backend_url="http://127.0.0.1:0", station_key="stn_test.secret")


class _EventCollector:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def broadcast(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


def _one_passing_phase():
    @htf.measures("step_outcome")
    @htf.PhaseOptions(name="TRIVIAL")
    def _phase(test):
        test.measurements["step_outcome"] = "PASS"
        return htf.PhaseResult.CONTINUE

    return [_phase]


@pytest.mark.asyncio
async def test_start_run_executes_and_reports_done(monkeypatch, credentials):
    monkeypatch.setattr(runner_module.plan_builder, "build_plan", lambda run_id, backend, **kw: _one_passing_phase())
    collector = _EventCollector()
    loop = asyncio.get_running_loop()
    runner = StationTestRunner(credentials=credentials, main_loop=loop, broadcast=collector.broadcast)

    try:
        runner.start_run("run-1")
        for _ in range(100):
            status = runner.get_status("run-1")
            if status["station_status"] in {"DONE", "ERROR"}:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("run did not complete in time")

        assert status["station_status"] == "DONE"
        assert status["result"] is True
    finally:
        runner.shutdown()


@pytest.mark.asyncio
async def test_start_run_while_busy_raises(monkeypatch, credentials):
    def slow_plan(run_id, backend, **kw):
        @htf.PhaseOptions()
        def _phase(test):
            time.sleep(0.3)
            return htf.PhaseResult.CONTINUE
        return [_phase]

    monkeypatch.setattr(runner_module.plan_builder, "build_plan", slow_plan)
    collector = _EventCollector()
    loop = asyncio.get_running_loop()
    runner = StationTestRunner(credentials=credentials, main_loop=loop, broadcast=collector.broadcast)

    try:
        runner.start_run("run-1")
        with pytest.raises(StationBusyError):
            runner.start_run("run-2")
        await asyncio.sleep(0.35)  # let the background phase finish before the loop closes, avoids a harmless late-broadcast log
    finally:
        runner.shutdown()


@pytest.mark.asyncio
async def test_get_status_idle_for_unknown_run(credentials):
    loop = asyncio.get_running_loop()
    collector = _EventCollector()
    runner = StationTestRunner(credentials=credentials, main_loop=loop, broadcast=collector.broadcast)
    try:
        assert runner.get_status("does-not-exist")["station_status"] == "IDLE"
    finally:
        runner.shutdown()


@pytest.mark.asyncio
async def test_pause_rejected_during_unsafe_phase(monkeypatch, credentials):
    def unsafe_plan(run_id, backend, **kw):
        @htf.PhaseOptions()
        def _phase(test):
            time.sleep(0.3)
            return htf.PhaseResult.CONTINUE
        return [_phase]

    monkeypatch.setattr(runner_module.plan_builder, "build_plan", unsafe_plan)
    collector = _EventCollector()
    loop = asyncio.get_running_loop()
    runner = StationTestRunner(credentials=credentials, main_loop=loop, broadcast=collector.broadcast)

    try:
        runner.start_run("run-1")
        await asyncio.sleep(0.05)
        with runner._lock:
            runner._active.current_step_type = "WIFI_PROVISION_BLE"
        with pytest.raises(PauseRejectedError):
            runner.request_pause("run-1")
        await asyncio.sleep(0.3)  # let the background phase finish before the loop closes, avoids a harmless late-broadcast log
    finally:
        runner.shutdown()


@pytest.mark.asyncio
async def test_events_broadcast_to_main_loop(monkeypatch, credentials):
    def plan_with_event(run_id, backend, *, on_event=None, **kw):
        @htf.measures("step_outcome")
        @htf.PhaseOptions(name="LED_RED")
        def _phase(test):
            if on_event:
                on_event("phase.started", "LED_RED", {})
            test.measurements["step_outcome"] = "PASS"
            if on_event:
                on_event("phase.completed", "LED_RED", {"status": "PASS"})
            return htf.PhaseResult.CONTINUE

        return [_phase]

    monkeypatch.setattr(runner_module.plan_builder, "build_plan", plan_with_event)
    collector = _EventCollector()
    loop = asyncio.get_running_loop()
    runner = StationTestRunner(credentials=credentials, main_loop=loop, broadcast=collector.broadcast)

    try:
        runner.start_run("run-1")
        for _ in range(100):
            if runner.get_status("run-1")["station_status"] in {"DONE", "ERROR"}:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)  # let the run.completed broadcast land
        event_types = [e for e, _ in collector.events]
        assert "phase.started" in event_types
        assert "phase.completed" in event_types
        assert "run.completed" in event_types
    finally:
        runner.shutdown()
