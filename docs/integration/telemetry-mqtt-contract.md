# QBox Telemetry MQTT Contract v1

Base namespace:

```text
qbox/v1/devices/{device_id}
```

Device publishes:

```text
/state
/heartbeat
/telemetry/system
/telemetry/network
/telemetry/components
/telemetry/services
/events/device
/events/hardware
/events/camera
/events/locker
/events/connectivity
/events/software
/events/security
/diagnostics
/acks/#
```

Standard event fields:

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "event_type": "camera.disconnected",
  "device_id": "QBOX-000001",
  "timestamp": "2026-09-01T00:00:00Z",
  "severity": "ERROR",
  "component": {"id": "camera.csi", "type": "camera"},
  "correlation_id": "uuid",
  "causation_id": null,
  "sequence_number": 1,
  "boot_id": "linux-boot-id",
  "data": {}
}
```

Backend ingestion is idempotent for `(device, event_id)`.
