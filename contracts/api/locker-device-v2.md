# Locker device contract v2 (signed access tokens, device API)

Status: **PROPOSAL — not approved; do not implement on either side until the hardware repository approves.**

- Proposed: 2026-10-04
- Supersedes: nothing. `contracts/api/locker-device-v1.md` (DRAFT) stays supported in parallel (§12).
- Why a new major version: v2 changes access-token semantics. v1 tokens are opaque random strings that only
  the backend can check. v2 tokens are Ed25519-signed and the device can verify them offline. Workspace
  `AGENTS.md` §12 and `contracts/README.md` treat a change to token meaning or authentication semantics as
  breaking.
- Owners: the backend owns token issuance, keys, authorization state, custody, incidents and evidence
  retention. The hardware repository owns scanning, local verification, actuation, the local used-nonce
  store, event capture, evidence capture and offline behavior. Neither side imports the other's code
  (`AGENTS.md` §3).
- Marker convention: **`UNKNOWN — VERIFY`** marks anything this document could not confirm from the
  backend code or the hardware repository's docs. The hardware team must resolve these before approval.

---

## 0. Change-discipline header (`AGENTS.md` §16)

```text
Repository:        contracts/ (workspace). Implementation later in Qbox-Backend and Qbox-Hardware, separately.
Ownership:         Backend = issuance/keys/authorization/custody/evidence storage. Hardware = scan/verify/actuate/report.
Reason:            Offline-capable one-time door codes, multi-compartment support, batched/ordered events,
                   HTTPS fallback for commands, evidence upload.
Contract involved: locker-device v1 (API), mqtt/device-control-plane-v1, device-onboarding/v1 (heartbeat).
Expected interface: HTTPS + mTLS endpoints under /api/v1/devices/…, additive heartbeat fields, two new
                   command types on the existing command channel.
```

---

## 1. Conventions

### 1.1 Transport, authentication, versioning

- **Device authentication is unchanged:** mutual TLS. nginx terminates TLS and forwards the verified client
  certificate. The backend resolves the device through the existing `DeviceCertificateAuthentication`: the
  certificate CN is the `device_uid` and the SHA-256 fingerprint must match an `ACTIVE`/`EXPIRING` device
  certificate, sent only from a trusted proxy. The certificate comes from the onboarding flow
  (`contracts/device-onboarding/v1.md`). User JWTs, API keys and anonymous callers get `401`/`403` on every
  endpoint in this document.
- The signed-request alternative (master prompt §4.4: device-key request signature + timestamp + nonce) is
  **out of scope** for v2. If it is ever needed, it gets its own contract.
- Every v2 request MUST send `X-QBox-Contract-Version: 2`, following the onboarding contract's
  `X-QBox-Contract-Version` pattern. When the header is missing or not `2`, the request is rejected with
  `400 CONTRACT_VERSION_UNSUPPORTED`.
- Content type is `application/json; charset=utf-8`. Timestamps are RFC 3339 in UTC with a `Z` suffix
  (`2026-10-04T10:00:00Z`). Device-originated timestamps come from the device clock and always travel with
  `clock_synced` (§3.6).
- Unknown JSON fields MUST be ignored by both sides. This is what makes additive changes to v2 compatible.

### 1.2 Response envelope (existing backend envelope)

Success:

```json
{"success": true, "message": "…", "data": { }, "meta": null}
```

Error. This is the existing `QboxAPIError` rendering. `code` and `detail` are copied to the top level, and
clients branch on `errors.code`, never on `message`:

```json
{"success": false, "message": "Invalid access authorization.",
 "errors": {"code": "ACCESS_TOKEN_INVALID", "detail": "Invalid access authorization.", "reason": "EXPIRED"},
 "code": "ACCESS_TOKEN_INVALID", "detail": "Invalid access authorization.", "meta": null}
```

`errors.reason` is a v2 addition, returned **only to mTLS-authenticated devices**, so the device can choose
local feedback and record telemetry. Public portal endpoints keep v1's deliberately uniform errors.

The body that authentication failures from `DeviceCertificateAuthentication` produce (`401`, codes such as
`DEVICE_CERTIFICATE_VERIFICATION_FAILED`) is shaped by the global DRF exception handler, so it may not match
this envelope exactly: **UNKNOWN — VERIFY.** Devices MUST branch on the HTTP status for `401`/`403` auth
failures.

### 1.3 Error codes used in this contract

| HTTP | `errors.code` | Status | Meaning |
|---|---|---|---|
| 400 | `VALIDATION_FAILED` | existing | Malformed body; `errors.fields` lists offending fields. |
| 400 | `CONTRACT_VERSION_UNSUPPORTED` | **new** | Missing or wrong `X-QBox-Contract-Version`. |
| 403 | `ACCESS_TOKEN_INVALID` | existing | Token rejected. `errors.reason` gives the cause (§4.3). |
| 403 | `DEVICE_NOT_ACTIVE` | **new** | Device authenticated but not allowed to operate locker functions (e.g. `SUSPENDED`, `RMA`, `RETIRED`). |
| 404 | `NOT_FOUND` | existing | Unknown command or evidence id, or one belonging to another device. |
| 409 | `DOOR_BUSY` | existing | Another authorization on the same compartment is open and not closed. |
| 409 | `EVIDENCE_UPLOAD_INCOMPLETE` | **new** | `complete` was called but the object is missing in storage. |
| 413 | `EVIDENCE_TOO_LARGE` | **new** | Declared `size_bytes` is above the limit for its kind. |
| 415 | `EVIDENCE_TYPE_NOT_ALLOWED` | **new** | `content_type` is not on the allowlist. |
| 422 | `EVIDENCE_CHECKSUM_MISMATCH` | **new** | The stored object's SHA-256 differs from the declared one. |
| 422 | `IDEMPOTENCY_KEY_REUSED` | existing | Same `sync_id`/`scan_id` sent again with a different body. |
| 429 | `RATE_LIMITED` | existing | Back off. Honor `Retry-After`. |
| 503 | — | — | Backend unavailable. Treated as "offline" for §4.4. |

New codes are added to the backend `ERROR_CATALOG` only when the backend implements this contract.

### 1.4 Route placement note (backend-internal, informative)

The existing backend already routes `/api/v1/devices/<str:device_uid>/…` for operator APIs. The literal
segments in this contract must be matched **before** the `<device_uid>` pattern, and must be reserved so
they can never be used as a `device_uid`: `keys`, `tokens`, `events`, `commands`, `offline-sync`,
`evidence`. If the backend prefers a separate prefix instead, changing the path before approval is a
contract change. Decide it during review.

---

## 2. Compartments (multi-compartment model)

- A compartment is identified by a **stable `index`** and a **human `label`**:
  - `index`: integer `0..254`, unique per device, fixed for the life of the device by its factory layout,
    never reused. `255` is reserved.
  - `label`: string of 1–16 characters (`[A-Z0-9-]`), e.g. `A1`. It is shown to people and may be
    re-labelled by the backend. It is **never** used as a key in tokens, events or commands.
- The backend sends the authoritative compartment list to the device in `GET /api/v1/devices/keys/`
  (`binding.compartments`, §5.2).
- **Current hardware:** the hardware repository's docs describe one solenoid output (relay IN3 → GPIO16),
  i.e. one door, so current devices have exactly one compartment, `index 0`. The v1 `component_key: "door"`
  maps to `index 0`. Whether any multi-compartment hardware exists or is planned is
  **UNKNOWN — VERIFY**.
- The backend already stores a free-text `compartment_key` on executions and access sessions. Mapping it to
  `index` is backend-internal.

---

## 3. Signed access token (v2)

### 3.1 Purposes

| v2 `purpose` | Code | Who | v1 equivalent | Default expiry (backend-configurable) |
|---|---|---|---|---|
| `DELIVERY` | `1` | Carrier driver, deposits | `DELIVERY` | End of issuing local day (Asia/Riyadh), as v1 |
| `PICKUP` | `2` | Carrier driver, removes outbound | `PICKUP` | End of pickup window / local day, as v1 |
| `OWNER_DEPOSIT` | `3` | Qbox owner, deposits outbound | `DROPOFF` | Owner TTL (v1 backend: 30 min; master prompt §4.5: 10 min. Owner to pick.) |
| `OWNER_COLLECT` | `4` | Qbox owner, removes inbound | `COLLECTION` | Owner TTL, as above |

Codes `0` and `5..255` are reserved. A device MUST reject them.

### 3.2 Binary payload layout (exactly 38 bytes)

All integers are unsigned and big-endian.

| Offset | Size | Field | Encoding / rule |
|---|---|---|---|
| 0 | 1 | `v` | Token format version. Always `0x02` for this contract. |
| 1 | 1 | `purpose` | §3.1 code. |
| 2 | 4 | `kid` | Key id. Opaque 4 bytes, written as 8 lowercase hex chars in JSON (`"3f9a1c07"`). |
| 6 | 7 | `qbox` | `qbox_code`, ASCII, uppercase, exactly as assigned, including the hyphen (`ABC-234`). Owner decision (master prompt §15.2): the 7-char `ABC-234` format stays. |
| 13 | 1 | `compartment` | Compartment `index` (§2). |
| 14 | 8 | `ref` | Opaque subject reference: random bytes the backend maps to the shipment, or to the pickup batch for `PICKUP`. **Never** derived from an AWB, phone, name or database id. In JSON: base64url without padding (11 chars). |
| 22 | 4 | `exp` | Expiry, Unix seconds (uint32, valid to 2106). |
| 26 | 12 | `nonce` | 96 random bits from a CSPRNG, unique per token. In JSON: base64url without padding (16 chars). |

`signature` = Ed25519 (RFC 8032, pure Ed25519, no pre-hash) over **exactly bytes 0–37**, i.e. 64 bytes.
Access-token signing keys are used for nothing else, and the version byte separates domains for future
formats.

`token_bytes = payload (38) || signature (64)` = 102 bytes.

### 3.3 String / QR encoding

```text
token = "Q2." || base64url_nopad(token_bytes)        ; 3 + 136 = 139 ASCII characters, always
```

- The `Q2.` prefix tells formats apart without guessing. v1 tokens are 32-character URL-safe random strings
  (alphabet `A–Z a–z 0–9 - _`), which never contain `.`. A device that supports both MUST branch on the
  prefix (§12.3).
- The QR code encodes the 139-character token string **only**, with no URL, in byte mode.
- QR size: at error-correction level **M**, 139 bytes need **QR version 8** (49×49 modules; capacity 152
  bytes). At level L they need version 7 (45×45; capacity 154 bytes). The recommendation is **level M**,
  because the QR is usually shown on a phone screen with glare and partial occlusion.
- Why binary rather than canonical JSON: the same claims as canonical JSON plus a base64url signature come
  to about 300+ characters (QR version 13–14 at level M, 69–73 modules per side). That roughly doubles the
  module count, which shrinks each module on a phone screen and makes camera reads harder at a fixed
  distance. The binary layout is fixed-length, so parsing needs no JSON parser and has no
  canonicalization ambiguity.
- Possible size reduction (open question Q1): RFC 9285 base45 in QR alphanumeric mode gives a
  153-character string that fits **version 7 at level M**. It is not adopted by default because base64url
  is URL- and JSON-safe and easier to log and debug. Adopt base45 only if the hardware team's camera tests
  show version 8 is unreliable.
- Whether the device's camera and QR decoder can read a version-8 QR from a phone screen, at what distance,
  and in what light is **UNKNOWN — VERIFY**. The hardware docs say camera capture is validated with
  `rpicam-still`/`ffmpeg`, but that "production camera pipeline and QR agent processes are not yet
  independently packaged services."

### 3.4 Test vector (TEST KEY ONLY, never deploy)

```text
private seed (hex)  000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
public key (b64url) A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg
kid                 3f9a1c07
purpose             1 (DELIVERY)
qbox                ABC-234
compartment         0
ref (hex)           a1b2c3d4e5f60718           -> b64url obLD1OX2Bxg
exp                 1791320399                  -> 2026-10-06T20:59:59Z
nonce (hex)         00112233445566778899aabb   -> b64url ABEiM0RVZneImaq7
payload (hex)       02013f9a1c074142432d32333400a1b2c3d4e5f607186ac5614f00112233445566778899aabb
signature (hex)     4bf3192f55d449a8d2d84b2ffa61787d11ec2b4f8bc0b48d20f8dc013bb47cad
                    340e48a7fd24a8148cdff44ec196d20ce167922b71fabc5580e4df2cd9fa4105
token (139 chars)   Q2.AgE_mhwHQUJDLTIzNAChssPU5fYHGGrFYU8AESIzRFVmd4iZqrtL8xkvVdRJqNLYSy_6YXh9EewrT4vAtI0g-NwBO7R8rTQOSKf9JKgUjN_0TsGW0gzhZ5Ircfq8VYDk3yzZ-kEF
```

Both repositories should reproduce this vector in their own test suites. Each side implements it
independently, with no shared code.

### 3.5 Device verification rules (apply in this order; first failure stops)

| # | Check | Reject `reason` |
|---|---|---|
| 1 | String starts with `Q2.`, is exactly 139 characters, decodes as base64url to exactly 102 bytes | `MALFORMED` |
| 2 | `v == 0x02` | `MALFORMED` |
| 3 | `kid` is in the cached keyset with status `NEXT`, `ACTIVE` or `GRACE` and inside that key's `not_before`/`not_after` | `UNKNOWN_KID` |
| 4 | Ed25519 signature verifies over bytes 0–37 | `BAD_SIGNATURE` |
| 5 | `qbox` equals `binding.qbox_code`, byte for byte | `WRONG_QBOX` |
| 6 | `compartment` is in `binding.compartments` | `UNKNOWN_COMPARTMENT` |
| 7 | `purpose` is in `1..4` (and in `policy.offline_purposes` when verifying offline) | `PURPOSE_NOT_ALLOWED` |
| 8 | Clock is trusted (§3.6), `now ≤ exp + clock_skew_seconds` and `exp ≤ now + max_token_ttl_seconds + clock_skew_seconds` | `EXPIRED` / `CLOCK_UNTRUSTED` |
| 9 | `nonce` is not in `revocations` (§5.2) | `REVOKED` |
| 10 | `nonce` is not in the local used-nonce store (§3.7) | `USED` |

- **Online** (§4.4 decides online vs offline): the device MAY run checks 1–10 locally to drop garbage
  early. It MUST then call `POST /api/v1/devices/tokens/verify/` and actuate **only** on that response.
- **Offline:** when checks 1–10 all pass, the device MUST first write the nonce to the used-nonce store
  **durably** (write-ahead and flush to persistent storage), **then** actuate. If the store write fails, it
  MUST NOT actuate (fail closed).
- Rejected tokens are never burned on the device, so a token scanned at the wrong Qbox stays valid for the
  right one. The same holds online (v1 rule kept).
- Local user feedback on rejection (LED/buzzer pattern) is hardware-owned and not specified here.
- Devices MUST NOT log full tokens. Log `token_digest` = first 16 hex chars of SHA-256(token string).

### 3.6 Clock and skew

- `clock_skew_seconds` comes from the keyset policy. Proposed default: **300**.
- A clock is **trusted** if it was synchronized from a network time source since boot, or if a battery-backed
  RTC that was set from a trusted source holds the time. Without a trusted clock, the device MUST NOT verify
  offline (`CLOCK_UNTRUSTED`). Online verification is unaffected because the server checks expiry.
- What clock source the device has (NTP/chrony/systemd-timesyncd, RTC presence on Pi 4/CM4 carrier) and how
  the runtime exposes "synchronized" is **UNKNOWN — VERIFY** (Q4).
- Every device-originated record carries `clock_synced: boolean` so the server can weigh device timestamps.

### 3.7 Offline used-nonce store

- Entry: `{nonce (12 B), exp (uint32), kid, compartment, purpose, used_at, scan_id, token_digest, synced: bool}`.
- Retention: keep an entry until **both** `synced == true` **and** `now > exp + clock_skew_seconds`. After
  that, check 8 rejects the token anyway, so the entry is no longer needed.
- Capacity: `policy.used_nonce_capacity`, proposed default **4096** entries (about 100 B each, under
  0.5 MB). Check 8 caps token lifetime at `max_token_ttl_seconds` (proposed default 129600 = 36 h), which
  bounds the live set.
- If the store is full of entries that are still unsynced or unexpired, the device MUST stop verifying
  offline (fail closed). It MUST NOT evict live entries.
- The store must survive power loss and reboot. A rollback of the store (restoring an old copy) would allow
  replay, so the hardware team must say how the store is protected (Q3). The hardware docs mention local
  SQLite-backed state; whether that store is suitable, and whether it is integrity-protected, is
  **UNKNOWN — VERIFY**.

---

## 4. Online verification — `POST /api/v1/devices/tokens/verify/`

### 4.1 Request

```json
{
  "token": "Q2.AgE_mhwH…",
  "scan_id": "6f0d3c1e-6a43-4c55-9b77-2d1a8f0e4b21",
  "scanned_at": "2026-10-04T10:00:00Z",
  "clock_synced": true,
  "local_check": "PASSED"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `token` | string | yes | v2 string (139 chars, `Q2.` prefix) **or** a v1 opaque token (§4.5). |
| `scan_id` | string (UUID) | yes | Generated by the device per physical scan. Idempotency key: unique per `(device, scan_id)`. |
| `scanned_at` | string (RFC 3339) | yes | Device clock. |
| `clock_synced` | boolean | yes | §3.6. |
| `local_check` | enum `PASSED` \| `FAILED` \| `SKIPPED` | no | Telemetry only. The server always verifies fully. |

### 4.2 Success — `200`

```json
{
  "success": true,
  "message": "Unlock authorized.",
  "data": {
    "decision": "UNLOCK",
    "authorization_reference": "8a1f6c2e-0b9d-4f0e-9a51-3f3c2b7d9e10",
    "purpose": "DELIVERY",
    "compartment": {"index": 0, "label": "A1"},
    "command": {
      "command_id": "c5e1b8f2-7d44-4a2b-8e6a-5b9f0d1c2a33",
      "type": "LOCK_UNLOCK",
      "parameters": {"compartment_index": 0, "duration_ms": 3000},
      "expires_at": "2026-10-04T10:02:00Z"
    },
    "evidence": {"requested": true, "kinds": ["PHOTO"]}
  },
  "meta": {"token_format": 2}
}
```

Server-side semantics:

1. The server verifies signature, `kid`, `qbox_code` against **the authenticated device's** Qbox,
   compartment, purpose, expiry, revocation and burn state. A valid token shown to another Qbox gets
   `WRONG_QBOX` and is **not** burned (v1 rule).
2. The server checks that no other authorization on the same compartment is `OPENED` and not closed
   (otherwise `409 DOOR_BUSY`). v1 checked this per device; v2 checks it per compartment.
3. The server **burns the nonce** and creates the authorization (v1 `QboxAccessSession` semantics:
   authorized, waiting for `OPEN_CONFIRMED`). This is the master prompt's "pending use". The nonce stays
   burned whatever happens physically. If the door fails to open, the device reports `OPEN_FAILED`, the
   authorization is revoked, and a new token must be issued (v1 rule).
4. **Inline command:** the server records a `LOCK_UNLOCK` `DeviceCommand` (`correlation_id` =
   `authorization_reference`) and returns it **in this response** instead of publishing it on MQTT, which
   would risk a double pulse. Its status is `DISPATCHED` at creation. The device acks it exactly like any
   other command (§7.3 or MQTT `command-ack`). This is a backend change from v1, where scan created a
   command that was dispatched over MQTT.
5. The device MUST NOT actuate after `command.expires_at` (allowing `clock_skew_seconds`).
6. Retrying with the same `scan_id` and an identical body returns the identical `200` (same
   `authorization_reference` and `command_id`) and creates no second command. Same `scan_id` with a
   different `token` → `422 IDEMPOTENCY_KEY_REUSED`.

### 4.3 Errors

| HTTP | `errors.code` | `errors.reason` | Burned? |
|---|---|---|---|
| 403 | `ACCESS_TOKEN_INVALID` | `MALFORMED`, `UNKNOWN_KID`, `BAD_SIGNATURE` | no |
| 403 | `ACCESS_TOKEN_INVALID` | `WRONG_QBOX`, `UNKNOWN_COMPARTMENT` | no |
| 403 | `ACCESS_TOKEN_INVALID` | `EXPIRED`, `REVOKED` | no (already dead) |
| 403 | `ACCESS_TOKEN_INVALID` | `USED` (already burned by a different scan) | — |
| 409 | `DOOR_BUSY` | — | no |
| 403 | `DEVICE_NOT_ACTIVE` | — | no |
| 429 | `RATE_LIMITED` | — | no |

A second scan of a burned token (`USED` from a different `scan_id`) is logged and raises a security alert
(master prompt §4.5).

### 4.4 Online vs offline decision (device)

- Verify **online** whenever the backend is reachable. The server is authoritative for burn, revocation and
  door-busy state.
- Fall back to **offline** verification (§3.5) only if all of these hold:
  - the HTTPS call failed with a network error, a timeout (proposed: 5 s connect + 5 s read, configurable on
    the device), or `502/503/504`;
  - `policy.offline_verification_enabled` is `true` in the last keyset fetched;
  - the clock is trusted;
  - the keyset is not older than `policy.max_keyset_age_seconds` (proposed default 7 days).
- A `4xx` from the server is final: never fall back to offline after a `403`/`409`.
- **Lost response:** if the request reached the server (nonce burned) but the response was lost, and the
  device then opened offline, the device reports the use in offline-sync with the **same `scan_id`**. The
  server matches `(device, scan_id, nonce)` and treats it as the same use (`ACCEPTED_DUPLICATE`), not as an
  incident (§8.3).

### 4.5 Relation to v1 `POST /api/v1/shipments/portal/device/scan/`

- v1 `scan/` and `door-events/` stay unchanged for v1 devices (§12).
- `tokens/verify/` also accepts **v1 opaque tokens**. The server detects the format from the `Q2.` prefix.
  For a v1 token the server does the v1 HMAC lookup, and the response shape is identical to §4.2 with
  `meta.token_format: 1`. A v2 device therefore needs only this endpoint. v1 tokens can never be verified
  offline.
- `scan_id` (v2) plays the same role as `device_event_id` in v1 `scan/`.

---

## 5. Keys — `GET /api/v1/devices/keys/`

### 5.1 Request

`GET /api/v1/devices/keys/` (mTLS, `X-QBox-Contract-Version: 2`). It supports `If-None-Match: "<etag>"` and
returns `304` with no body when nothing changed.

### 5.2 Response — `200` (header `ETag: "keyset-17"`)

```json
{
  "success": true,
  "message": "OK",
  "data": {
    "keyset_version": 17,
    "issued_at": "2026-10-04T09:00:00Z",
    "keys": [
      {"kid": "41c0de55", "alg": "Ed25519", "public_key": "<b64url 32 bytes>", "status": "NEXT",
       "not_before": "2026-10-05T00:00:00Z", "not_after": null},
      {"kid": "3f9a1c07", "alg": "Ed25519", "public_key": "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",
       "status": "ACTIVE", "not_before": "2026-09-01T00:00:00Z", "not_after": null},
      {"kid": "77aa0b12", "alg": "Ed25519", "public_key": "<b64url 32 bytes>", "status": "GRACE",
       "not_before": "2026-08-01T00:00:00Z", "not_after": "2026-10-06T12:00:00Z"}
    ],
    "binding": {
      "device_uid": "qbox-7f3a…",
      "qbox_code": "ABC-234",
      "compartments": [{"index": 0, "label": "A1"}]
    },
    "policy": {
      "clock_skew_seconds": 300,
      "max_token_ttl_seconds": 129600,
      "offline_verification_enabled": true,
      "offline_purposes": ["DELIVERY", "PICKUP", "OWNER_DEPOSIT", "OWNER_COLLECT"],
      "used_nonce_capacity": 4096,
      "max_keyset_age_seconds": 604800,
      "keys_refresh_seconds": 21600
    },
    "revocations": [
      {"nonce": "ABEiM0RVZneImaq7", "exp": 1791320399}
    ]
  },
  "meta": null
}
```

| Field | Type | Notes |
|---|---|---|
| `keys[].kid` | string, 8 hex | Matches token bytes 2–5. |
| `keys[].alg` | `"Ed25519"` | Only this value in v2. |
| `keys[].public_key` | string | base64url, no padding, 32 raw bytes. |
| `keys[].status` | `NEXT` \| `ACTIVE` \| `GRACE` | All three are valid for verification. Only `ACTIVE` signs new tokens. |
| `keys[].not_before` / `not_after` | RFC 3339 / null | Validity window for verification. |
| `binding.qbox_code` | string | The device compares token `qbox` against this. Whether the device already knows its `qbox_code` from onboarding/configuration is **UNKNOWN — VERIFY**. This endpoint makes it authoritative. |
| `binding.compartments` | array | §2. |
| `policy.*` | — | Device-tunable limits, all server-owned. |
| `revocations` | array | Nonces of tokens **for this Qbox** that the backend revoked and that are not yet expired. The device rejects them offline (check 9) and may drop entries after `exp + clock_skew_seconds`. |

Device behavior:

- Refresh every `keys_refresh_seconds`, on boot, and on `SYNC_KEYS` (§7.4).
- Replace the cached keyset **atomically** (write temp, flush, rename). Keep the last good keyset on any
  failure.
- If the cached keyset is older than `max_keyset_age_seconds`, stop verifying offline.
- **UNKNOWN — VERIFY:** the hardware docs do not describe a hardware secure element or TPM. Public keys are
  not secret, but whether keyset integrity at rest (tamper resistance) matters is part of Q3.

### 5.3 Rotation and grace

1. **Pre-publish:** the backend creates a new key as `NEXT` at least **24 h** (proposed) before it starts
   signing with it, so offline devices learn it ahead of time.
2. **Promote:** `NEXT` → `ACTIVE`, and the old `ACTIVE` → `GRACE` with
   `not_after = promotion_time + max_token_ttl_seconds + clock_skew_seconds`. Every token the old key
   signed has expired by then.
3. **Retire:** after `not_after`, the key is removed from the list.
4. Each change bumps `keyset_version`. The backend then sends `SYNC_KEYS` to every online device. Devices
   offline at the time pick up the change on their periodic refresh.
5. **Emergency (key compromise):** the key is removed immediately (no grace), a new `ACTIVE` key is issued,
   `SYNC_KEYS` is fanned out, and offline verification may be disabled fleet-wide through policy. Accepted
   residual risk: a device that stays offline keeps trusting the compromised key until it syncs. Its
   offline uses surface in offline-sync as `UNKNOWN_KID`/`BAD_SIGNATURE` incidents (§8.3).
6. Private keys live only in the backend secrets store (master prompt §4.5). Signing is a backend concern.

---

## 6. Door events — `POST /api/v1/devices/events/`

### 6.1 Request (batch)

```json
{
  "events": [
    {
      "event_id": "0b6c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d",
      "boot_id": "e2a4…-uuid",
      "seq": 1042,
      "type": "OPEN_CONFIRMED",
      "compartment": {"index": 0},
      "authorization_reference": "8a1f6c2e-0b9d-4f0e-9a51-3f3c2b7d9e10",
      "local_authorization_id": null,
      "occurred_at": "2026-10-04T10:00:03Z",
      "clock_synced": true,
      "monotonic_ms": 8812345,
      "details": {}
    }
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `events` | array, 1–100 items | yes | More than 100 → `400 VALIDATION_FAILED`. |
| `event_id` | string (UUID) | yes | Unique per device, forever. **Idempotency key: `(device, event_id)`.** |
| `boot_id` | string (UUID) | yes | A new random value each boot. |
| `seq` | integer (uint64) | yes | Strictly increasing within a `boot_id`, starting at 1. Devices SHOULD keep it monotonic across reboots too (persisted counter). Whether the runtime can do this is **UNKNOWN — VERIFY**. |
| `type` | enum §6.2 | yes | |
| `compartment.index` | integer | yes | §2. |
| `authorization_reference` | string (UUID) \| null | conditional | Required for `OPEN_CONFIRMED`, `CLOSED_CONFIRMED` and `OPEN_FAILED` when the cause was an online verification. |
| `local_authorization_id` | string (UUID) \| null | conditional | Used **instead of** `authorization_reference` for offline unlocks (§8). |
| `occurred_at` | RFC 3339 | yes | Device clock. |
| `clock_synced` | boolean | yes | §3.6. |
| `monotonic_ms` | integer | no | Milliseconds since boot. Orders events within a boot even if wall-clock time jumps. |
| `details` | object | no | Type-specific, §6.2. |

### 6.2 Event types

| `type` | Meaning | Authorization link | Server effect |
|---|---|---|---|
| `OPEN_CONFIRMED` | Door physically opened after an authorized unlock | required | Session → `OPENED`; owner notified for **every** opening (v1). Evidence recording expected. |
| `CLOSED_CONFIRMED` | Door physically closed (and relocked) after an authorized opening | required | Custody move per v1 §4.2 table. The **only** proof of physical deposit or removal. |
| `OPEN_FAILED` | Unlock was actuated but the door did not open (or actuation failed) | required | Authorization revoked; a new token is needed (v1). `details.cause`: `ACTUATOR_FAULT` \| `NOT_OPENED_IN_TIME` \| `OTHER`. |
| `DOOR_LEFT_OPEN` | Door still open after the device's local timeout | optional | Device alert + owner notification once per session (v1). The backend still raises its own timeout (`QBOX_DOOR_CLOSE_TIMEOUT_SECONDS`, 120 s). `details.open_seconds`. |
| `FORCED_OPEN` | Door opened with **no** active authorized unlock | none | Security incident (critical), owner + ops notified, evidence requested. |
| `TAMPER` | Tamper detected | none | Security incident. `details.source`: `ENCLOSURE` \| `CAMERA_OBSTRUCTED` \| `POWER` \| `OTHER`. |

**Hardware dependency (UNKNOWN — VERIFY):** `OPEN_CONFIRMED`, `CLOSED_CONFIRMED`, `DOOR_LEFT_OPEN` and
`FORCED_OPEN` need a real door-position sensor. The hardware docs say: "GPIO17 is reported as
`secondary_gpio`. Unless it is proven to be a real lock state feedback signal, the preflight reports
`verified_state=UNKNOWN`", and "never treats a GPIO command as proof of physical lock state." A device
without a verified door sensor MUST NOT emit these events from commanded state alone. The backend's
`DOOR_SENSOR` capability key exists, but whether current hardware has one is unconfirmed. Which `TAMPER`
sources exist is also **UNKNOWN — VERIFY**.

### 6.3 Response — `200` (per-event results)

```json
{
  "success": true,
  "message": "Events processed.",
  "data": {
    "results": [
      {"event_id": "0b6c1d2e-…", "status": "ACCEPTED", "authorization_reference": "8a1f6c2e-…",
       "session_status": "OPENED"},
      {"event_id": "1c7d…", "status": "DUPLICATE", "session_status": "OPENED"},
      {"event_id": "2d8e…", "status": "REJECTED", "code": "ACCESS_TOKEN_INVALID",
       "detail": "Unknown access authorization."}
    ],
    "high_water": {"boot_id": "e2a4…-uuid", "seq": 1042}
  },
  "meta": null
}
```

- `status`: `ACCEPTED` | `DUPLICATE` (seen before; nothing re-applied) | `REJECTED` (permanently invalid; do
  **not** retry).
- The device deletes an event from its outbox only once it has `ACCEPTED`, `DUPLICATE` or `REJECTED` for
  it. On a transport error or `5xx`, it retries the whole batch. Idempotency makes that safe.
- `high_water` is the highest contiguous `seq` the server has stored for that `boot_id`. It is informative
  and helps the device detect gaps.

### 6.4 Ordering and out-of-order rules (server)

- Server ordering key: `(boot_id, seq)` within a boot. Across boots: `occurred_at` when `clock_synced`,
  otherwise arrival order. Every event is stored with `received_at`.
- State transitions are **monotonic and never regress**. A late `OPEN_CONFIRMED` (lower `seq`) arriving
  after `CLOSED_CONFIRMED` for the same authorization is stored and notified (the owner still learns of the
  opening) but does not move the session back to `OPENED`.
- If `CLOSED_CONFIRMED` arrives with no prior `OPEN_CONFIRMED`, the server implies the opening: custody
  moves, and an implied `OPEN_CONFIRMED` is recorded for the audit trail.
- Events for a closed or revoked authorization are stored for audit and do not change custody, except an
  `OPEN_CONFIRMED` after `OPEN_FAILED` for the same authorization, which raises a security alert.
- Device-side ordering: within one compartment, the device MUST assign `seq` in the order physical state
  changes were observed.

---

## 7. Commands over HTTPS (fallback to MQTT)

MQTT stays the primary push channel (`qbox/v1/devices/{device_uid}/commands`, acks on `…/command-ack`,
`contracts/mqtt/device-control-plane-v1.md`). HTTPS polling is a fallback for when MQTT is down, plus a
low-rate safety net.

### 7.1 Command types

| `type` | Existing? | Parameters | Expected `result` on `COMPLETED` |
|---|---|---|---|
| `LOCK_UNLOCK` | existing (`UNLOCK`, expiry 2 min) | `duration_ms` int 500–15000 (default 3000, existing). **v2 adds** `compartment_index` int (default `0`) and `authorization_reference` UUID \| null. | `{"compartment_index": 0, "actuated": true}` |
| `DEVICE_REBOOT` | existing (`REBOOT`, expiry 2 min) | `delay_seconds` number 0.5–30 (default 2, existing) | ack `ACKNOWLEDGED` before rebooting; `COMPLETED` is optional |
| `PING` | **new** | none | `{"received_at": "…", "uptime_seconds": 1234, "contract_versions": {…}}` |
| `SYNC_KEYS` | **new** | `{"min_keyset_version": 17}` | `{"keyset_version": 17, "kids": ["41c0de55","3f9a1c07","77aa0b12"]}` after a successful `GET /keys/` |

Other existing command types (`ALARM_CONTROL`, `RUN_TEST`, connectivity commands) are unchanged and may also
arrive through polling. A device that does not support a type acks `FAILED` with
`error_code: "UNSUPPORTED_COMMAND"`. Existing in-flight conflict rules (e.g. `DEVICE_REBOOT` blocks
`LOCK_UNLOCK`) stay on the backend. The rate limits and expiry for `PING`/`SYNC_KEYS` are backend-owned:
proposed 5 min expiry, deduplicated per device.

### 7.2 Poll — `GET /api/v1/devices/commands/?limit=20`

```json
{
  "success": true,
  "message": "OK",
  "data": {
    "commands": [
      {"command_id": "c5e1…", "type": "LOCK_UNLOCK", "status": "DISPATCHED",
       "parameters": {"compartment_index": 0, "duration_ms": 3000, "authorization_reference": null},
       "created_at": "2026-10-04T10:00:00Z", "expires_at": "2026-10-04T10:02:00Z",
       "correlation_id": null}
    ]
  },
  "meta": {"next_poll_seconds": 15}
}
```

- Returns this device's commands in `PENDING` or `DISPATCHED` that have not expired, oldest first.
  `limit` is 1–50, default 20.
- Returning a `PENDING` command moves it to `DISPATCHED`. A command may already have gone out over MQTT;
  both channels can deliver the same `command_id`.
- **Device dedupe (MUST):** execute each `command_id` at most once. Keep executed ids for at least
  24 h / the last 256 ids.
- The device MUST NOT execute a command after `expires_at` (allowing `clock_skew_seconds`). It acks such a
  command `FAILED` with `error_code: "EXPIRED_ON_DEVICE"`.
- Poll cadence: honor `meta.next_poll_seconds`. Proposed: 15 s while MQTT is disconnected, 300 s while
  connected.
- Sensitive parameters (e.g. Wi-Fi passwords in connectivity commands) are handled as on MQTT today. Whether
  HTTPS polling may carry `encrypted_secrets` is an open backend decision (§13, Q-B3).

### 7.3 Ack — `POST /api/v1/devices/commands/{command_id}/ack/`

```json
{"status": "COMPLETED", "result": {"compartment_index": 0, "actuated": true},
 "message": "", "error_code": "", "acked_at": "2026-10-04T10:00:02Z", "clock_synced": true}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | `ACKNOWLEDGED` \| `COMPLETED` \| `FAILED` | yes | Same values as the MQTT `command-ack` payload the backend already consumes (`command_id`, `status`, `result`, `message`, `error_code`). |
| `result` | object | no | Type-specific, §7.1. |
| `message`, `error_code` | string | no | Required when `FAILED`. |
| `acked_at` | RFC 3339 | yes | Device clock. |

Response `200`:

```json
{"success": true, "message": "OK",
 "data": {"command_id": "c5e1…", "status": "COMPLETED", "applied": true}, "meta": null}
```

- **Idempotent.** Once a command is final (`COMPLETED`/`FAILED`/`EXPIRED`/`CANCELLED`), later acks return
  `200` with the stored `status` and `applied: false`. This matches the existing backend, which ignores acks
  on final commands.
- An ack over MQTT and an ack over HTTPS for the same command are equivalent. The first one to reach a
  final state wins.
- Unknown command, or a command belonging to another device → `404 NOT_FOUND`.

### 7.4 Status mapping (existing `DeviceCommandStatus`)

```text
PENDING ──(MQTT publish | HTTPS poll | inline verify response)──▶ DISPATCHED
DISPATCHED ──ack ACKNOWLEDGED──▶ ACKNOWLEDGED
DISPATCHED | ACKNOWLEDGED ──ack COMPLETED──▶ COMPLETED
DISPATCHED | ACKNOWLEDGED ──ack FAILED──▶ FAILED
PENDING | DISPATCHED | ACKNOWLEDGED ──server timeout──▶ EXPIRED
any non-final ──superseded/cancelled by backend──▶ CANCELLED   (existing status, backend-only)
```

The device never sends `PENDING`, `DISPATCHED`, `EXPIRED` or `CANCELLED`. A device may go straight to
`COMPLETED`/`FAILED` without `ACKNOWLEDGED`, as the current MQTT command processor already does.

---

## 8. Offline sync — `POST /api/v1/devices/offline-sync/`

### 8.1 Request

```json
{
  "sync_id": "5a9e…-uuid",
  "boot_id": "e2a4…-uuid",
  "offline_from": "2026-10-04T08:00:00Z",
  "offline_to": "2026-10-04T11:30:00Z",
  "token_uses": [
    {
      "local_authorization_id": "9d0e…-uuid",
      "scan_id": "6f0d3c1e-…",
      "token": "Q2.AgE_mhwH…",
      "kid": "3f9a1c07",
      "nonce": "ABEiM0RVZneImaq7",
      "purpose": "DELIVERY",
      "compartment": {"index": 0},
      "exp": 1791320399,
      "used_at": "2026-10-04T09:12:00Z",
      "clock_synced": true,
      "keyset_version": 17
    }
  ],
  "events": [
    {"event_id": "…", "boot_id": "e2a4…", "seq": 1043, "type": "OPEN_CONFIRMED",
     "compartment": {"index": 0}, "authorization_reference": null,
     "local_authorization_id": "9d0e…-uuid", "occurred_at": "2026-10-04T09:12:04Z",
     "clock_synced": true, "details": {}}
  ]
}
```

- `sync_id`: idempotency key per `(device, sync_id)`. A replay with an identical body returns the stored
  result. A different body → `422 IDEMPOTENCY_KEY_REUSED`.
- `token_uses`: at most 500. `events`: at most 500, same schema as §6.1. Larger backlogs go in several
  syncs, oldest first.
- The full `token` is required, so the server re-verifies the signature itself and does not trust the
  device's claims about it. `kid`, `nonce`, `purpose`, `compartment` and `exp` are redundant
  cross-checks; any mismatch with the decoded token → incident `TOKEN_FIELDS_MISMATCH`.
- `token_uses` lists only tokens the device **accepted and actuated** offline. Offline rejections are
  reported as telemetry. They are not part of this contract.
- Events in the same sync that reference a `local_authorization_id` are applied **after** the
  corresponding token use.

### 8.2 Response — `200`

```json
{
  "success": true,
  "message": "Offline sync processed.",
  "data": {
    "token_uses": [
      {"local_authorization_id": "9d0e…", "status": "ACCEPTED",
       "authorization_reference": "b3c4…-uuid", "incident": null}
    ],
    "events": [
      {"event_id": "…", "status": "ACCEPTED", "authorization_reference": "b3c4…-uuid"}
    ],
    "keys_stale": false
  },
  "meta": null
}
```

- `token_uses[].status`: `ACCEPTED` | `ACCEPTED_DUPLICATE` | `INCIDENT`.
- `events[].status`: as in §6.3.
- `keys_stale: true` means the device's `keyset_version` is behind. The device then calls
  `GET /api/v1/devices/keys/`.
- After a `200`, the device marks the reported nonces `synced` (§3.7) and drops the reported events from its
  outbox. The door has already opened, so the server **never** answers "reject, close the door". It records
  the facts and raises incidents.

### 8.3 Server conflict rules

| Situation | Status | Incident code | Effect |
|---|---|---|---|
| Valid signature, right Qbox, nonce not burned, not revoked, `used_at ≤ exp + skew` | `ACCEPTED` | — | Burn the nonce, create the authorization (`OPENED` if `OPEN_CONFIRMED` follows), apply events and custody normally, notify the owner. |
| Nonce burned earlier **by this device with the same `scan_id`** (lost online response, §4.4) | `ACCEPTED_DUPLICATE` | — | Map to the existing `authorization_reference`. Nothing applied twice. |
| Nonce already burned (online or offline, any device, different `scan_id`), or the same nonce twice in one sync | `INCIDENT` | `NONCE_REUSED` | **Security incident.** The door already opened. Events are stored for audit. Custody changes from this use are **held for ops review** and not applied automatically. Owner and ops notified. |
| Token revoked server-side **before** `used_at` (e.g. a newer code was issued for the same parcel) | `INCIDENT` | `REVOKED_TOKEN_USED_OFFLINE` | **Security incident**, door already opened. Events stored. Custody held for review (owner decision Q-B1). Owner and ops notified. |
| `used_at > exp + skew`, or `clock_synced == false` | `INCIDENT` | `EXPIRED_TOKEN_ACCEPTED` / `UNTRUSTED_CLOCK_USE` | Device policy violation. Incident + device alert. Custody held for review. |
| Signature invalid, `kid` unknown or retired, or `qbox`/compartment not matching this device | `INCIDENT` | `INVALID_TOKEN_ACCEPTED` | **Critical:** possible device compromise or emergency key rotation. Device alert, and the device may be moved to review/suspension by ops. Custody not applied. |
| Decoded token fields differ from the reported fields | `INCIDENT` | `TOKEN_FIELDS_MISMATCH` | Critical, as above. |

Incidents are backend records (alert + audit). How they are presented in panels is backend-owned.

---

## 9. Evidence — `POST /api/v1/devices/evidence/`

### 9.1 Request an upload slot

```json
{
  "kind": "PHOTO",
  "content_type": "image/jpeg",
  "size_bytes": 482113,
  "sha256": "9f2c…64 hex",
  "captured_at": "2026-10-04T10:00:04Z",
  "clock_synced": true,
  "camera": "EXTERNAL",
  "compartment": {"index": 0},
  "event_ids": ["0b6c1d2e-…"],
  "authorization_reference": "8a1f6c2e-…",
  "local_authorization_id": null
}
```

| Field | Type | Rule |
|---|---|---|
| `kind` | `PHOTO` \| `VIDEO` | |
| `content_type` | string | Allowlist: `image/jpeg` (PHOTO), `video/mp4` (VIDEO, H.264). Anything else → `415 EVIDENCE_TYPE_NOT_ALLOWED`. |
| `size_bytes` | integer | PHOTO ≤ 2 MiB, VIDEO ≤ 25 MiB and ≤ 30 s (proposed defaults, backend-configurable). Over the limit → `413 EVIDENCE_TOO_LARGE`. |
| `sha256` | string, 64 hex | Checked on completion. |
| `camera` | `EXTERNAL` \| `INTERNAL` | Matches the backend capability keys `CSI_CAMERA_EXTERNAL`/`CSI_CAMERA_INTERNAL`. Hardware docs also mention a USB camera; how cameras map to roles is **UNKNOWN — VERIFY**. |
| `event_ids` | array of strings, 1–10 | Event ids this evidence documents. The events may be uploaded later; links resolve when they arrive. |
| `authorization_reference` / `local_authorization_id` | UUID \| null | Optional direct link. |

### 9.2 Response — `201`

```json
{
  "success": true,
  "message": "Upload slot created.",
  "data": {
    "evidence_id": "e7f8…-uuid",
    "upload": {
      "method": "PUT",
      "url": "https://<private-bucket-presigned-url>",
      "headers": {"Content-Type": "image/jpeg", "x-amz-checksum-sha256": "<base64 sha256>"},
      "expires_at": "2026-10-04T10:15:04Z"
    }
  },
  "meta": null
}
```

- The upload goes **directly to private object storage** using the pre-signed URL. That URL carries no
  device credential and expires after 15 minutes (proposed). The exact storage provider and header names
  depend on the backend's storage backend: **UNKNOWN — VERIFY** (backend-side).
- At most 50 open (uncompleted) slots per device (proposed). Beyond that → `429 RATE_LIMITED`.
- Requesting a slot is idempotent per `(device, sha256)`: re-requesting returns the same `evidence_id`
  with a fresh URL.

### 9.3 Complete — `POST /api/v1/devices/evidence/{evidence_id}/complete/`

Body `{}`. The backend checks that the object exists and that its size and checksum match.

- `200` → `{"evidence_id": "…", "status": "STORED"}`. The device may now delete its local copy.
- `409 EVIDENCE_UPLOAD_INCOMPLETE` (object missing) or `422 EVIDENCE_CHECKSUM_MISMATCH` → the device
  re-uploads, requesting a new slot if the URL expired.

### 9.4 Ownership

- **Retention, access control, legal hold and deletion are owned by the backend.** The device keeps evidence
  only until `complete` returns `200`, or until its own local storage limit evicts it (hardware-owned
  policy).
- Evidence never contains a token or anything decodable from a QR. The device MUST NOT burn a QR into an
  image overlay.
- Whether the device can record **video** (not only stills), and how fast it can start recording on
  `OPEN_CONFIRMED`, is **UNKNOWN — VERIFY**. The hardware docs confirm only single-frame capture tests.

---

## 10. Heartbeat additions (per-compartment state, capability announcement)

There is **no new heartbeat endpoint.** The existing channels carry these fields:
`POST /api/v1/device-onboarding/heartbeat/` and the MQTT `qbox/v1/devices/{device_uid}/heartbeat` envelope
(`payload`). The fields are **additive** to those v1 contracts, so neither contract needs a new version.
The master prompt's `POST /devices/heartbeat/` is deliberately not added, to avoid two heartbeat paths.

```json
{
  "contract_versions": {
    "locker-device": ["1", "2"],
    "mqtt-control-plane": ["1"],
    "device-onboarding": ["1"]
  },
  "compartments": [
    {"index": 0, "label": "A1", "door": "CLOSED", "lock": "LOCKED",
     "door_source": "SENSOR", "lock_source": "COMMANDED",
     "last_change_at": "2026-10-04T10:00:30Z"}
  ],
  "locker_access": {
    "keyset_version": 17,
    "offline_verification_ready": true,
    "used_nonce_entries": 12,
    "unsynced_nonce_entries": 0,
    "pending_events": 0,
    "pending_evidence": 1,
    "clock_synced": true
  }
}
```

| Field | Values | Rule |
|---|---|---|
| `door` | `OPEN` \| `CLOSED` \| `UNKNOWN` | `UNKNOWN` unless a verified door sensor exists. |
| `lock` | `LOCKED` \| `UNLOCKED` \| `UNKNOWN` | |
| `door_source` / `lock_source` | `SENSOR` \| `COMMANDED` \| `NONE` | `COMMANDED` means "last command sent", **not** a physical reading. The backend MUST NOT treat it as proof (matches the hardware docs' `verified_state=UNKNOWN` rule). |
| `contract_versions` | object of string arrays | Capability negotiation, §12.2. |

---

## 11. Idempotency and ordering summary

| Endpoint | Idempotency key | Replay behavior |
|---|---|---|
| `POST tokens/verify/` | `(device, scan_id)` | Same response, no second command or burn. |
| `POST events/` | `(device, event_id)` per event | `DUPLICATE`, nothing re-applied. |
| `POST commands/{id}/ack/` | `(command_id)` + final state | `applied: false` after final. |
| `POST offline-sync/` | `(device, sync_id)` + per-item `local_authorization_id`/`event_id` | Stored result. |
| `POST evidence/` | `(device, sha256)` | Same `evidence_id`, fresh URL. |
| `POST evidence/{id}/complete/` | `evidence_id` | `200 STORED` again. |
| `GET keys/`, `GET commands/` | — | Safe reads. `GET commands/` moves `PENDING` → `DISPATCHED` (idempotent). |

Ordering: `(boot_id, seq)` within a boot; transitions are monotonic and never regress (§6.4). Offline token
uses are applied before events that reference them (§8.1).

---

## 12. Migration and compatibility

### 12.1 Coexistence

- v1 (`portal/device/scan/`, `portal/device/door-events/`, opaque tokens) remains supported, unchanged, for
  every device that does not announce `locker-device: "2"`.
- v2 endpoints are new paths. Nothing in v1 changes meaning. The public portal response
  (`POST /api/v1/shipments/portal/{qbox_code}/deliver|pickup/`) keeps `qr_token`, whose value is either a
  v1 or a v2 token. An **additive** `token_format: 1|2` field can be added to the v1 portal contract.
- A token is issued in v2 format **only** when the target device has announced `locker-device: "2"` in its
  latest heartbeat **and** the per-device/per-fleet rollout flag (backend-owned) is on. Otherwise the token
  is v1.

### 12.2 Capability negotiation

- The device announces `contract_versions` in every heartbeat (§10). The backend stores the latest
  announcement per device.
- A v2-capable device MUST keep accepting v1 tokens (branch on `Q2.`) for as long as v1 is supported. It
  verifies them online through `tokens/verify/` (§4.5) or the v1 `scan/`.
- If a device downgrades, e.g. its announcement drops `"2"` after an OTA rollback, the backend stops issuing
  v2 tokens for it immediately. v2 tokens already issued but unused are still verified online by the server
  until they expire. To avoid a dead code, the portal SHOULD re-issue such tokens on request.

### 12.3 Rollout

1. Backend ships v2 endpoints and the keyset behind a flag, with no tokens issued as v2. Simulator coverage
   per master prompt §4.6 (`qbox_simulate_device`) for verify, events, offline-sync and evidence.
2. Hardware ships v2 support, announces `locker-device: ["1","2"]`, fetches keys, and still receives only
   v1 tokens.
3. Backend enables v2 issuance for pilot devices with **offline verification disabled** by policy (online
   only).
4. Offline verification is enabled for pilots, then the fleet, after incident review.
5. v1 is deprecated only after every active device announces `"2"`, plus a notice period (proposed 90 days)
   documented in the v1 file.

### 12.4 Rollback

- **Soft:** turn the issuance flag off. New tokens become v1. Outstanding v2 tokens stay valid online, and
  offline until `exp`.
- **Offline only:** set `policy.offline_verification_enabled=false` and send `SYNC_KEYS`.
- **Hard (key compromise):** emergency rotation, §5.3 step 5.
- The device keeps v1 support throughout, so it never needs a rollback of its own.

---

## 13. Open questions

### For the hardware team (blocking approval)

- **Q1 — Camera QR limits.** Can the production camera and decoder reliably read a **version-8, level-M**
  byte-mode QR (49×49 modules) from a phone screen? At what distance and in what lighting, and with which
  camera (CSI external vs USB)? If not, is version 7 alphanumeric (base45) acceptable? Which decoder library
  and frame rate will be used?
- **Q2 — Ed25519 on the device runtime.** Will Ed25519 verification be available on the production
  runtime? The hardware repo declares Python ≥3.12 and `cryptography==45.0.6`, which supports Ed25519 when
  built against OpenSSL ≥1.1.1, but availability on the shipped image is **UNKNOWN — VERIFY**. What is the
  verification latency on Pi 4 / CM4?
- **Q3 — Secure storage of the used-nonce list and keyset.** Where will they live (the hardware docs mention
  local SQLite state)? How is a write made durable before actuation under power loss? Can rollback (an
  older copy restored) be detected, e.g. with a monotonic counter, TPM/secure element, or a signed
  high-water mark? Is a 4096-entry capacity acceptable?
- **Q4 — Clock source.** NTP client in use? RTC on the production carrier? How does the runtime expose
  "synchronized since boot"? Expected drift while offline?
- **Q5 — Door and lock sensing.** Is there a verified door-position sensor per compartment? Is GPIO17 a real
  lock-feedback signal? Without one, `OPEN_CONFIRMED`/`CLOSED_CONFIRMED`/`FORCED_OPEN`/`DOOR_LEFT_OPEN`
  cannot be emitted honestly, and v1's custody rule (only `CLOSED_CONFIRMED` moves custody) cannot be met.
- **Q6 — Multi-compartment hardware.** Is any multi-door model planned? How many compartments at most, and
  is a uint8 index enough?
- **Q7 — Tamper sources.** Which tamper inputs exist (enclosure switch, camera obstruction detection, power
  loss)?
- **Q8 — Evidence capture.** Can the device record video, and with what codec, resolution and start
  latency? Local evidence buffer size? Which camera faces the compartment interior?
- **Q9 — Persistent sequence counter.** Can `seq` be persisted across reboots, and is a per-boot `boot_id`
  available?
- **Q10 — Device knowledge of `qbox_code`.** Does the device already store its `qbox_code` from
  onboarding/configuration, or will `GET /keys/` `binding` be its only source?
- **Q11 — Offline policy defaults.** Should any purpose (e.g. `PICKUP`, which may cover many parcels) be
  excluded from offline verification by default?

### For the backend / owner (non-blocking for hardware review)

- **Q-B1** — For a revoked token used offline (benign revocation such as a code re-issued for the same
  parcel), should custody move automatically or stay held for review? The proposal holds it for review.
- **Q-B2** — Owner token TTL: 30 min (current backend) or 10 min (master prompt §4.5)?
- **Q-B3** — May HTTPS command polling deliver commands with encrypted secrets (connectivity
  credentials)?
- **Q-B4** — Route placement: literal segments under `/api/v1/devices/` (reserved `device_uid` values) or a
  separate prefix (§1.4)?
- **Q-B5** — Evidence storage provider and pre-signed header scheme; retention periods per evidence kind.
