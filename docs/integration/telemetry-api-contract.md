# QBox Telemetry API Contract v1

All endpoints require authentication and existing device access authorization.
Responses use the backend `StandardAPIResponse` envelope.

```text
GET /api/v1/devices/{device_id}/telemetry/overview/
GET /api/v1/devices/{device_id}/telemetry/
GET /api/v1/devices/{device_id}/components/
GET /api/v1/devices/{device_id}/components/{component_id}/
GET /api/v1/devices/{device_id}/health/overview/
GET /api/v1/devices/{device_id}/events/
GET /api/v1/devices/{device_id}/events/{event_id}/
GET /api/v1/devices/{device_id}/alerts/
GET /api/v1/devices/{device_id}/alerts/{alert_id}/
POST /api/v1/devices/{device_id}/alerts/{alert_id}/acknowledge/
POST /api/v1/devices/{device_id}/alerts/{alert_id}/resolve/
GET /api/v1/devices/{device_id}/diagnostics/
GET /api/v1/devices/{device_id}/diagnostics/{diagnostic_id}/
POST /api/v1/devices/{device_id}/diagnostics/run/
```

Telemetry history is bounded with `limit` capped at 500.
