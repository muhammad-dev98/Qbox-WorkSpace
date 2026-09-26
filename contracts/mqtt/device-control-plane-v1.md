# QBox MQTT Device Control Plane v1

Status: active  
Last updated: August 30, 2026

Topic version prefix:

- `qbox/v1`

Identity rule:

- `{device_uid}` is authoritative and immutable once registered

## Device publishes

- `qbox/v1/devices/{device_uid}/telemetry`
- `qbox/v1/devices/{device_uid}/events`
- `qbox/v1/devices/{device_uid}/heartbeat`
- `qbox/v1/devices/{device_uid}/state`
- `qbox/v1/devices/{device_uid}/command-ack`
- `qbox/v1/devices/{device_uid}/configuration-ack`

## Device subscribes

- `qbox/v1/devices/{device_uid}/commands`
- `qbox/v1/devices/{device_uid}/configuration`

## Envelope requirements

Heartbeat and other message-envelope traffic use:

- `message_id`
- `device_uid`
- `message_type`
- `timestamp`
- `schema_version`
- `payload`

The backend currently supports `schema_version = 1`.

