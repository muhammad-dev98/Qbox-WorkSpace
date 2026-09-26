# QBox Camera and Live Streaming Audit

## Existing Implementation

Backend `cameras` currently includes a non-production media path:

- `cameras/views.py` imports OpenCV and NumPy in Django workers.
- `CameraLiveStreamAPIView`, `CameraStreamAPIView`, `live_stream`, and
  `generate_stream` use `StreamingHttpResponse` for MJPEG.
- `CameraFrameUploadAPIView`, `get_frame`, and `upload_frame` accept camera
  frames into Django and store them in process memory through `cameras/streamer.py`.
- `CameraSerializer` exposes RTSP and WebRTC URLs directly.
- `permission_classes = [AllowAny]` is used on camera and stream endpoints.
- `templates/camera_viewer.html` and `templates/camera_player.html` embed static
  stream paths and browser assumptions.
- `setup-pi4-streaming.sh` lives in the backend repository even though Pi setup
  and stream publishing are hardware responsibilities.

Hardware currently has safe camera preflight checks in the Raspberry Pi
controller but no dedicated camera manager, camera SQLite inventory, MediaMTX
publisher lifecycle, or stream watchdog.

## Problems

- Django is acting as a media proxy and frame store.
- Video can traverse Django request workers.
- MJPEG is used as a primary browser path.
- Camera frame upload endpoints are unauthenticated.
- Static camera IDs and paths are guessable.
- Backend exposes private media URLs.
- Hardware `/dev/video*` selection exists only in preflight diagnostics and is
  not a persistent camera identity model.
- MediaMTX configuration/setup lives in the wrong repository.

## APIs Removed or Replaced

Removed from production route surface:

- `/cameras/live/{camera_id}/`
- `/cameras/frame/{camera_id}/`
- `/cameras/stream/{camera_id}/`
- `/cameras/view/{camera_id}/`
- `/cameras/start-stream/`
- `/cameras/stop-stream/`

Replacement control-plane API:

- `GET /api/v1/cameras/qboxes/{qbox_id}/cameras/`
- `GET /api/v1/cameras/qboxes/{qbox_id}/cameras/{camera_id}/`
- `GET /api/v1/cameras/qboxes/{qbox_id}/cameras/{camera_id}/health/`
- `POST /api/v1/cameras/qboxes/{qbox_id}/cameras/{camera_id}/live-session/`
- `DELETE /api/v1/cameras/qboxes/{qbox_id}/cameras/{camera_id}/live-session/{session_uid}/`

## Final Replacement Architecture

```text
CSI -> rpicam/libcamera H264 -> RTSP/RTP -> MediaMTX -> WebRTC -> browser
USB -> V4L2/H264 or hardware encoder -> RTSP/RTP -> MediaMTX -> WebRTC -> browser
```

Django remains the control plane only. Hardware owns discovery, local inventory,
publisher processes, watchdogs, and MediaMTX publishing. Backend owns camera
metadata, authorization, short-lived live sessions, audit state, and API
contracts.
