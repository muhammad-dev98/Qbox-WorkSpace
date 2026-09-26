from __future__ import annotations

from typing import Any

import requests

from .config import StationCredentials


class BackendError(Exception):
    """
    Raised for any non-2xx backend response. `is_connectivity_error` lets
    callers (dispatched_step phases, BLE-native phases) distinguish
    "backend unreachable / 5xx" from "the backend rejected this request" -
    the former must never be recorded as a step FAIL (see the durable
    crash-recovery work planned for a later phase); it is surfaced here so
    callers can retry rather than misreport a network blip as a hardware
    failure.
    """

    def __init__(self, code: str, message: str, *, status_code: int | None = None, is_connectivity_error: bool = False):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.is_connectivity_error = is_connectivity_error


class BackendClient:
    """
    Synchronous (requests-based, not aiohttp) HTTP client the Station uses
    to talk to Qbox-Backend's factory_ops API as itself (X-Station-Key),
    not on behalf of an operator. Synchronous because OpenHTF phases
    execute on a plain worker thread (see runner.py), not the aiohttp event
    loop this process also runs for the Panel-facing local server - there
    is no benefit to bridging every call back onto that loop.
    """

    def __init__(self, credentials: StationCredentials, *, timeout: float = 15.0):
        self._credentials = credentials
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["X-Station-Key"] = credentials.station_key

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self._credentials.backend_url}{path}"
        try:
            response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise BackendError("BACKEND_UNREACHABLE", str(exc), is_connectivity_error=True) from exc

        if response.status_code >= 500:
            raise BackendError(
                "BACKEND_SERVER_ERROR", f"{response.status_code} from {path}",
                status_code=response.status_code, is_connectivity_error=True,
            )
        if response.status_code >= 400:
            code = "BACKEND_REQUEST_FAILED"
            message = response.text
            try:
                body = response.json()
                error = body.get("error") if isinstance(body, dict) else None
                if isinstance(error, dict):
                    code = error.get("code", code)
                    message = error.get("message", message)
            except ValueError:
                pass
            raise BackendError(code, message, status_code=response.status_code)

        if not response.content:
            return None
        body = response.json()
        return body.get("data") if isinstance(body, dict) else body

    # -- Test-run / test-plan endpoints (Phase 3 wires these up backend-side) --

    def get_test_run(self, run_id: str) -> dict:
        return self._request("GET", f"/api/v1/factory/test-runs/{run_id}/")

    def get_profile_version_steps(self, version_id: str) -> list[dict]:
        return self._request("GET", f"/api/v1/factory/test-profile-versions/{version_id}/steps/")

    def dispatch_next_step(self, run_id: str) -> dict | None:
        return self._request("POST", f"/api/v1/factory/test-runs/{run_id}/dispatch-next-step/")

    def cancel_test_run(self, run_id: str, reason: str = "") -> dict:
        return self._request("POST", f"/api/v1/factory/test-runs/{run_id}/cancel/", json={"reason": reason})

    def begin_step(self, run_id: str, step_id: str) -> dict:
        return self._request("POST", f"/api/v1/factory/test-runs/{run_id}/steps/{step_id}/begin/")

    def submit_result(
        self,
        run_id: str,
        result_id: str,
        *,
        status: str,
        evidence_type: str,
        actual_values: dict | None = None,
        error_code: str = "",
        logs: str = "",
    ) -> dict:
        return self._request(
            "POST",
            f"/api/v1/factory/test-runs/{run_id}/results/{result_id}/submit/",
            json={
                "status": status,
                "evidence_type": evidence_type,
                "actual_values": actual_values or {},
                "error_code": error_code,
                "logs": logs,
            },
        )
