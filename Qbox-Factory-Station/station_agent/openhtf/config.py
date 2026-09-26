from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CREDENTIALS_PATH = Path.home() / ".config" / "qbox-factory-station" / "credentials.json"


class StationCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class StationCredentials:
    """
    What the Station needs to authenticate ITS OWN calls to the backend
    (X-Station-Key: <key_id>.<secret>, issued by `manage.py issue_station_key`
    on the backend - see Qbox-Backend/factory_ops/authentication.py). This is
    never sent to, or accepted from, the Factory Panel browser - see
    station_agent/local_auth.py for the separate mechanism that authenticates
    Panel -> Station calls.
    """

    backend_url: str
    station_key: str  # "<key_id>.<secret>", passed through verbatim as the header value

    @property
    def key_id(self) -> str:
        return self.station_key.split(".", 1)[0]


def load_credentials(*, backend_url: str | None = None, station_key: str | None = None) -> StationCredentials:
    """
    Resolution order: explicit args (CLI flags) -> environment
    (QBOX_BACKEND_URL / QBOX_STATION_KEY) -> local credentials file
    (~/.config/qbox-factory-station/credentials.json, written by whoever ran
    `issue_station_key` on the backend and copied the printed value here).
    """
    resolved_url = backend_url or os.environ.get("QBOX_BACKEND_URL")
    resolved_key = station_key or os.environ.get("QBOX_STATION_KEY")

    if not resolved_url or not resolved_key:
        file_values = _read_credentials_file()
        resolved_url = resolved_url or file_values.get("backend_url")
        resolved_key = resolved_key or file_values.get("station_key")

    if not resolved_url:
        raise StationCredentialsError(
            "No backend URL configured - pass --backend-url, set QBOX_BACKEND_URL, "
            f"or add 'backend_url' to {DEFAULT_CREDENTIALS_PATH}"
        )
    if not resolved_key or "." not in resolved_key:
        raise StationCredentialsError(
            "No valid station key configured - pass --station-key, set QBOX_STATION_KEY, "
            f"or add 'station_key' to {DEFAULT_CREDENTIALS_PATH}. "
            "Issue one on the backend with `manage.py issue_station_key <station_code>`."
        )
    if not resolved_url.startswith("https://") and not resolved_url.startswith("http://localhost") and not resolved_url.startswith("http://127.0.0.1"):
        raise StationCredentialsError(
            f"Refusing plaintext backend URL {resolved_url!r} - Station->Backend traffic must be HTTPS "
            "(loopback/localhost is allowed for local development only)."
        )

    return StationCredentials(backend_url=resolved_url.rstrip("/"), station_key=resolved_key)


def _read_credentials_file(path: Path = DEFAULT_CREDENTIALS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StationCredentialsError(f"Could not read credentials file {path}: {exc}") from exc
