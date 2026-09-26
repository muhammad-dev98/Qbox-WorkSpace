from __future__ import annotations

import argparse
import logging
import os

from .openhtf.config import StationCredentialsError, load_credentials
from .server import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="qbox-factory-station")
    parser.add_argument("--host", default=os.environ.get("QBOX_STATION_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("QBOX_STATION_PORT", "8787")))
    parser.add_argument("--station-id", default=os.environ.get("QBOX_STATION_ID", "FACTORY-STATION-001"))
    parser.add_argument("--backend-url", default=None, help="Overrides QBOX_BACKEND_URL / credentials file")
    parser.add_argument("--station-key", default=None, help="Overrides QBOX_STATION_KEY / credentials file")
    parser.add_argument(
        "--no-openhtf",
        action="store_true",
        help="Skip loading backend credentials - run BLE/WiFi provisioning only, no OpenHTF test-run endpoints",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )
    log = logging.getLogger(__name__)
    log.info("qbox_factory_station_starting host=%s port=%s station_id=%s", args.host, args.port, args.station_id)

    credentials = None
    if not args.no_openhtf:
        try:
            credentials = load_credentials(backend_url=args.backend_url, station_key=args.station_key)
        except StationCredentialsError as exc:
            log.warning("station_credentials_not_configured error=%s - starting without OpenHTF test-run support", exc)

    run(host=args.host, port=args.port, station_id=args.station_id, credentials=credentials)


if __name__ == "__main__":
    main()
