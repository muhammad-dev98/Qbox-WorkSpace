# QBox Telemetry Architecture

```text
QBox hardware/services/system -> TelemetryAgent -> SQLite durable queue -> MQTT
MQTT -> Qbox-Backend hardware_devices ingest -> persistence -> REST/WebSocket
```

Telemetry observes device owners such as camera, GPIO, locker, buzzer,
connectivity, registration, and services. It does not control those resources.

Hardware implementation:

- Observer: `qbox_platform.telemetry.TelemetryAgent`
- Durable queue: `qbox_platform.storage.AgentDatabase.event_queue`
- MQTT transport: `qbox_platform.transport.mqtt.MQTTManager`
- Component defaults: `qbox_platform.telemetry.collectors.COMPONENTS`

Backend implementation:

- Ingest service: `hardware_devices.services.observability_service.HardwareTelemetryService`
- Models: `DeviceComponent`, `DeviceHeartbeat`, `DeviceTelemetry`,
  `DeviceEvent`, `DeviceHealthSnapshot`, `DeviceDiagnostic`, `DeviceAlert`
- REST views: `hardware_devices.views.observability`

Physical health claims are not synthesized in software. Components without
readback use commanded/safe-check state.
