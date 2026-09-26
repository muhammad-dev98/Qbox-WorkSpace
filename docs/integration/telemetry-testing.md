# QBox Telemetry Testing

Automated software gates used in this workspace:

```text
Qbox-Hardware/.venv/bin/python -m pytest -q
Qbox-Backend/venv/bin/python manage.py check
Qbox-Backend/venv/bin/python manage.py makemigrations hardware_devices --check --dry-run
Qbox-Backend/venv/bin/python manage.py test hardware_devices.tests.test_observability_platform
```

Hardware tests cover topic construction, durable queue enqueue, system snapshot
construction, component defaults, event envelope fields, and existing
connectivity/BLE tests.

Backend tests cover MQTT ingest service behavior, event idempotency, alert
dedupe, heartbeat history, and REST authentication/overview behavior. In this
host the DB-backed backend tests cannot execute until PostgreSQL test database
access is available.
