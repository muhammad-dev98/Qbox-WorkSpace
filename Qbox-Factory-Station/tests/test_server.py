from __future__ import annotations

import base64
import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from station_agent import server as server_module
from station_agent.local_auth import LocalAuthError, OperatorPrincipal


def _fake_jwt(exp_in_seconds: float = 300) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + exp_in_seconds}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


class _FakeAuthenticator:
    """Stand-in for OperatorAuthenticator that never makes a real HTTP call to the backend."""

    def __init__(self, *, allow: bool = True, permissions=frozenset({"factory.read", "factory.update"})):
        self._allow = allow
        self._permissions = permissions

    async def authenticate(self, request):
        if not self._allow:
            raise LocalAuthError("LOCAL_AUTH_INVALID", "denied")
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise LocalAuthError("LOCAL_AUTH_MISSING", "missing")
        return OperatorPrincipal(user_id="user-1", permissions=self._permissions)


class _FakeRunner:
    def __init__(self):
        self.started = []
        self.aborted = []
        self.statuses = {}

    def start_run(self, run_id, *, ble_context=None):
        self.started.append((run_id, ble_context))

    def get_status(self, run_id):
        return self.statuses.get(run_id, {"run_id": run_id, "station_status": "IDLE"})

    def abort(self, run_id):
        self.aborted.append(run_id)

    def request_pause(self, run_id):
        pass

    def resume(self, run_id):
        pass

    def shutdown(self):
        pass


@pytest.fixture
async def client_with_auth(aiohttp_client):
    app = server_module.build_app(station_id="TEST-STATION")
    app["authenticator"] = _FakeAuthenticator(allow=True)
    app["runner"] = _FakeRunner()
    return await aiohttp_client(app)


@pytest.fixture
async def client_no_auth(aiohttp_client):
    # authenticator stays None -> middleware allows all requests through,
    # matching build_app()'s behavior when no credentials/backend are configured.
    app = server_module.build_app(station_id="TEST-STATION")
    app["runner"] = _FakeRunner()
    return await aiohttp_client(app)


async def test_missing_bearer_token_rejected(client_with_auth):
    resp = await client_with_auth.get("/station/status")
    assert resp.status == 401
    body = await resp.json()
    assert body["error"]["code"] == "LOCAL_AUTH_MISSING"


async def test_valid_bearer_token_allowed(client_with_auth):
    resp = await client_with_auth.get("/station/status", headers={"Authorization": f"Bearer {_fake_jwt()}"})
    assert resp.status == 200


async def test_denied_token_rejected(aiohttp_client):
    app = server_module.build_app(station_id="TEST-STATION")
    app["authenticator"] = _FakeAuthenticator(allow=False)
    app["runner"] = _FakeRunner()
    client = await aiohttp_client(app)
    resp = await client.get("/station/status", headers={"Authorization": f"Bearer {_fake_jwt()}"})
    assert resp.status == 401


async def test_no_authenticator_configured_allows_requests(client_no_auth):
    resp = await client_no_auth.get("/station/status")
    assert resp.status == 200


async def test_start_test_run_calls_runner(client_with_auth):
    resp = await client_with_auth.post(
        "/test-runs/run-1/start",
        headers={"Authorization": f"Bearer {_fake_jwt()}"},
        json={"ble_context": {"address": "AA:BB:CC"}},
    )
    assert resp.status == 202
    body = await resp.json()
    assert body["status"] == "STARTED"


async def test_test_run_status_returns_runner_state(client_with_auth, aiohttp_client):
    app = server_module.build_app(station_id="TEST-STATION")
    app["authenticator"] = _FakeAuthenticator(allow=True)
    fake_runner = _FakeRunner()
    fake_runner.statuses["run-1"] = {"run_id": "run-1", "station_status": "RUNNING", "phase": "LED_RED"}
    app["runner"] = fake_runner
    client = await aiohttp_client(app)

    resp = await client.get("/test-runs/run-1/status", headers={"Authorization": f"Bearer {_fake_jwt()}"})
    assert resp.status == 200
    body = await resp.json()
    assert body["station_status"] == "RUNNING"
    assert body["phase"] == "LED_RED"


async def test_abort_test_run_calls_runner(client_with_auth):
    resp = await client_with_auth.post("/test-runs/run-1/abort", headers={"Authorization": f"Bearer {_fake_jwt()}"})
    assert resp.status == 200
    body = await resp.json()
    assert body["aborted"] is True


async def test_no_runner_configured_returns_503(aiohttp_client):
    app = server_module.build_app(station_id="TEST-STATION")
    app["authenticator"] = _FakeAuthenticator(allow=True)
    client = await aiohttp_client(app)
    resp = await client.post("/test-runs/run-1/start", headers={"Authorization": f"Bearer {_fake_jwt()}"}, json={})
    assert resp.status == 503


class _FakeBackendClient:
    """Stands in for openhtf.backend_client.BackendClient - records calls
    instead of making a real HTTP request to the backend, same idea as
    _FakeAuthenticator above."""

    instances: list["_FakeBackendClient"] = []

    def __init__(self, credentials):
        self.credentials = credentials
        self.begin_calls: list[tuple[str, str]] = []
        self.submit_calls: list[tuple[str, str, dict]] = []
        type(self).instances.append(self)

    def begin_step(self, run_id, step_id):
        self.begin_calls.append((run_id, step_id))
        return {"test_result_id": "result-1", "attempt_number": 1, "run_status": "RUNNING"}

    def submit_result(self, run_id, result_id, *, status, evidence_type, actual_values=None, error_code="", logs=""):
        self.submit_calls.append((run_id, result_id, {"status": status, "evidence_type": evidence_type, "actual_values": actual_values, "error_code": error_code}))
        return {"test_result_id": result_id, "status": status}


async def test_begin_manual_step_uses_station_credentials(aiohttp_client, monkeypatch):
    # The manual/interactive BLE flow (BleProvisioningCard driven from the
    # Factory Panel's Test Workspace) records its outcome through this
    # route rather than a second, independent write path - it must reuse
    # the exact same StationCredentials-authenticated BackendClient the
    # automatic OpenHTF flow uses (see BackendClientPlug), never the
    # operator's own JWT (that only ever authorizes them to this LOCAL
    # station - see _auth_middleware).
    _FakeBackendClient.instances.clear()
    monkeypatch.setattr(server_module, "BackendClient", _FakeBackendClient)
    from station_agent.openhtf.config import StationCredentials

    app = server_module.build_app(station_id="TEST-STATION", credentials=StationCredentials(backend_url="https://backend.example", station_key="key-1.secret"))
    app["authenticator"] = _FakeAuthenticator(allow=True)
    client = await aiohttp_client(app)

    resp = await client.post("/test-runs/run-1/steps/step-1/begin", headers={"Authorization": f"Bearer {_fake_jwt()}"})
    assert resp.status == 200
    body = await resp.json()
    assert body["test_result_id"] == "result-1"
    assert _FakeBackendClient.instances[-1].begin_calls == [("run-1", "step-1")]


async def test_submit_manual_step_result_forwards_to_backend_client(aiohttp_client, monkeypatch):
    _FakeBackendClient.instances.clear()
    monkeypatch.setattr(server_module, "BackendClient", _FakeBackendClient)
    from station_agent.openhtf.config import StationCredentials

    app = server_module.build_app(station_id="TEST-STATION", credentials=StationCredentials(backend_url="https://backend.example", station_key="key-1.secret"))
    app["authenticator"] = _FakeAuthenticator(allow=True)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/test-runs/run-1/results/result-1/submit",
        headers={"Authorization": f"Bearer {_fake_jwt()}"},
        json={"status": "PASS", "evidence_type": "PHYSICAL", "actual_values": {"secure_session_id": "sess-1"}},
    )
    assert resp.status == 200
    call = _FakeBackendClient.instances[-1].submit_calls[-1]
    assert call[0] == "run-1"
    assert call[1] == "result-1"
    assert call[2]["status"] == "PASS"
    assert call[2]["actual_values"] == {"secure_session_id": "sess-1"}


async def test_submit_manual_step_result_rejects_missing_fields(aiohttp_client, monkeypatch):
    monkeypatch.setattr(server_module, "BackendClient", _FakeBackendClient)
    from station_agent.openhtf.config import StationCredentials

    app = server_module.build_app(station_id="TEST-STATION", credentials=StationCredentials(backend_url="https://backend.example", station_key="key-1.secret"))
    app["authenticator"] = _FakeAuthenticator(allow=True)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/test-runs/run-1/results/result-1/submit",
        headers={"Authorization": f"Bearer {_fake_jwt()}"},
        json={"status": "PASS"},
    )
    assert resp.status == 400


async def test_begin_manual_step_without_credentials_returns_503(aiohttp_client):
    app = server_module.build_app(station_id="TEST-STATION")
    app["authenticator"] = _FakeAuthenticator(allow=True)
    client = await aiohttp_client(app)

    resp = await client.post("/test-runs/run-1/steps/step-1/begin", headers={"Authorization": f"Bearer {_fake_jwt()}"})
    assert resp.status == 503
