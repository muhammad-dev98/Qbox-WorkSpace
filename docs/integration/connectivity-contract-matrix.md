# QBox Connectivity Contract Matrix

| Operation | App/API | Backend action | MQTT | Hardware action | BLE | Result |
|---|---|---|---|---|---|---|
| Read state | GET connectivity state | Read persisted state | `.../state` | Publish authoritative state | Status characteristic | `ONLINE`, `DEGRADED`, `OFFLINE`, or provisioning state |
| State update | Realtime/API read | Validate and persist | Hardware -> `.../state` | Collect local checks | Optional status notification | Cloud state updated |
| Event | Realtime/API history | Validate and persist audit event | Hardware -> `.../events` | Queue event offline | Optional notification | History item |
| Wi-Fi scan online | Scan command API | Create command | `.../commands` | Run local scan | Not required | Results via state/event contract |
| Wi-Fi scan offline | BLE session | Authorize session | None | Run local scan | Secure session scan operation | Incremental results required by GATT implementation |
| Wi-Fi change online | Command API | Authorize and expire command | `.../commands` | Candidate, verify, commit/rollback | Not required | Final event/state |
| Wi-Fi change offline | BLE session | Session authorization only | None | Candidate, verify, commit/rollback | Secure session connect operation | Final local state |
| Forget profile | Command API | Authorize command | `.../commands` | Delete requested profile | Optional authorized operation | Event/state |
| BLE recovery | Provisioning-session API | Issue short-lived token | Optional mode command | Enable recovery policy | Authenticate locally | Session expires/terminates |

Sensitive Wi-Fi credentials never appear in backend responses, normal MQTT
payloads, persisted connectivity state, or logs.
