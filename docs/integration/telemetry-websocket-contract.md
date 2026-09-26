# QBox Telemetry WebSocket Contract v1

Browser clients connect to backend WebSocket endpoints only. Devices never expose
browser-facing WebSockets.

Normalized frontend message shape:

```json
{
  "type": "component.status_changed",
  "timestamp": "2026-09-01T00:00:00Z",
  "device_id": "QBOX-000001",
  "data": {
    "component_id": "camera.csi",
    "status": "DEGRADED"
  }
}
```

Event types emitted by backend adapters:

```text
device.state_changed
device.health_changed
component.status_changed
telemetry.updated
device.event
device.alert_created
device.alert_updated
device.alert_resolved
diagnostic.started
diagnostic.completed
```

REST remains the recovery source after reconnect.
