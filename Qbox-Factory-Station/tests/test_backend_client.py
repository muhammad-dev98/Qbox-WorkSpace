from __future__ import annotations

import json as json_module

import pytest
import requests

from station_agent.openhtf.backend_client import BackendClient, BackendError
from station_agent.openhtf.config import StationCredentials


class _FakeResponse:
    def __init__(self, *, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text if not json_body else json_module.dumps(json_body)
        self.content = self.text.encode()

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


@pytest.fixture
def credentials():
    return StationCredentials(backend_url="https://backend.example.com", station_key="stn_abc.secret123")


def test_get_test_run_sends_station_key_header_and_unwraps_envelope(monkeypatch, credentials):
    captured = {}

    def fake_request(self, method, url, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(self.headers)
        return _FakeResponse(json_body={"data": {"id": "run-1", "status": "RUNNING"}})

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = BackendClient(credentials)
    result = client.get_test_run("run-1")

    assert result == {"id": "run-1", "status": "RUNNING"}
    assert captured["method"] == "GET"
    assert captured["url"] == "https://backend.example.com/api/v1/factory/test-runs/run-1/"
    assert captured["headers"]["X-Station-Key"] == "stn_abc.secret123"


def test_4xx_raises_backend_error_with_code_from_body(monkeypatch, credentials):
    def fake_request(self, method, url, timeout=None, **kwargs):
        return _FakeResponse(status_code=404, json_body={"error": {"code": "NOT_FOUND", "message": "no such run"}})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = BackendClient(credentials)

    with pytest.raises(BackendError) as excinfo:
        client.get_test_run("missing")
    assert excinfo.value.code == "NOT_FOUND"
    assert excinfo.value.is_connectivity_error is False


def test_5xx_raises_connectivity_backend_error(monkeypatch, credentials):
    def fake_request(self, method, url, timeout=None, **kwargs):
        return _FakeResponse(status_code=503, text="upstream down")

    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = BackendClient(credentials)

    with pytest.raises(BackendError) as excinfo:
        client.get_test_run("run-1")
    assert excinfo.value.is_connectivity_error is True


def test_connection_error_raises_connectivity_backend_error(monkeypatch, credentials):
    def fake_request(self, method, url, timeout=None, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = BackendClient(credentials)

    with pytest.raises(BackendError) as excinfo:
        client.get_test_run("run-1")
    assert excinfo.value.code == "BACKEND_UNREACHABLE"
    assert excinfo.value.is_connectivity_error is True


def test_submit_result_posts_expected_payload(monkeypatch, credentials):
    captured = {}

    def fake_request(self, method, url, timeout=None, **kwargs):
        captured["json"] = kwargs.get("json")
        captured["url"] = url
        return _FakeResponse(json_body={"data": {"ok": True}})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = BackendClient(credentials)
    client.submit_result("run-1", "result-1", status="PASS", evidence_type="PHYSICAL", actual_values={"a": 1})

    assert captured["url"].endswith("/api/v1/factory/test-runs/run-1/results/result-1/submit/")
    assert captured["json"]["status"] == "PASS"
    assert captured["json"]["evidence_type"] == "PHYSICAL"
    assert captured["json"]["actual_values"] == {"a": 1}
