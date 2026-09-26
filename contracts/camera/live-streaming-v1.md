# QBox Camera Live Streaming Contract v1

## Ownership

- Qbox-Hardware owns camera detection, health checks, capture, encoding, MediaMTX publishing, and local recovery.
- Qbox-Backend owns authorization, camera metadata state, live-session issuance, auditing, and app-facing REST APIs.
- The backend must not receive, proxy, decode, upload, store, or transcode camera frames.

## MQTT Topics

- Hardware publishes camera events to `qbox/v1/devices/{device_uid}/events/camera` with QoS 1.
- Payloads are JSON objects with `schema_version`, `event_type`, `timestamp`, and a domain body.

## Camera Inventory Event

`event_type`: `camera.inventory`

Required body:

```json
{
  "schema_version": 1,
  "event_type": "camera.inventory",
  "timestamp": "2026-09-01T00:00:00Z",
  "cameras": [
    {
      "camera_uid": "cam_...",
      "device_id": "QBOX-...",
      "camera_type": "CSI",
      "camera_role": "EXTERNAL",
      "status": "DETECTED",
      "enabled": true,
      "model": "imx708",
      "serial_number": "",
      "hardware_path": "csi://0"
    }
  ]
}
```

`camera_type` values: `CSI`, `USB`, `UNKNOWN`.

`camera_role` values: `EXTERNAL`, `INTERNAL`, `UNKNOWN`.

## Camera Streams Event

`event_type`: `camera.streams`

```json
{
  "schema_version": 1,
  "event_type": "camera.streams",
  "timestamp": "2026-09-01T00:00:00Z",
  "streams": [
    {
      "camera_uid": "cam_...",
      "stream_id": "cam_...:primary",
      "stream_role": "PRIMARY",
      "protocol": "WEBRTC",
      "codec": "h264",
      "resolution": "1280x720",
      "fps": 25,
      "bitrate": 2000000,
      "media_path": "qbox/QBOX-.../cameras/cam_...",
      "status": "RUNNING"
    }
  ]
}
```

The `media_path` is an internal MediaMTX path. The backend may use it to create a scoped playback endpoint, but must not expose RTSP ingest URLs or device-local paths.

## REST API

- `GET /api/v1/qboxes/{qbox_id}/cameras/`
- `GET /api/v1/qboxes/{qbox_id}/cameras/{camera_uid}/`
- `GET /api/v1/qboxes/{qbox_id}/cameras/{camera_uid}/health/`
- `POST /api/v1/qboxes/{qbox_id}/cameras/{camera_uid}/live-session/`
- `DELETE /api/v1/qboxes/{qbox_id}/cameras/{camera_uid}/live-session/{session_uid}/`

Live-session responses contain a short-lived playback token and a public WebRTC endpoint only. Plain tokens are never stored; only token hashes are persisted.
