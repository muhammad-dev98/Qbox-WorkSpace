# Stabilization round — 7 October 2026 (part 2: owner decisions 1–8)

## 1. EMQX dashboard exposure — fixed

**Before:** the EMQX dashboard and its API were reachable from the internet through nginx at `/emqx/`,
`/api/v1/emqx/` and the raw `/api/v5/`. The dashboard user `qbox` had a 4-character password. The backend's management
API settings used the same user and password.

**Who logged in (evidence):**
- nginx access logs cover 23 Sep – 7 Oct, the full retained history.
- **All 7 dashboard logins came from `103.229.253.64–.93`**, the owner's network: this office machine is
  `103.229.253.77`.
- The only other address, `149.102.244.115`, opened the dashboard page twice on 1 Oct, got a 502 and never logged in.
- No other address touched the raw `/api/v5/` path.
- EMQX keeps no log file of its own (it logs to the console), and its console log only goes back to the container
  restart on 5 Oct. There, no login activity was recorded.

**Done:**
- **New password:** a random 48-character password is set in EMQX (`emqx ctl admins passwd qbox …`) and in
  `.env.development` (dashboard and management API).
  - Checked: the new password logs in (200); the old one is rejected (401).
  - A root-only copy is in `/root/qbox-ops/secrets/emqx-dashboard.txt`. Read it with `ssh root@… cat …`; it is not
    printed anywhere.
- **Basic auth** (user `qbox-ops`) now sits in front of all 8 EMQX nginx locations.
  - Checked: without credentials all EMQX paths return 401; with credentials they reach EMQX; the rest of the site is
    unchanged.
  - Rollback copy: `/etc/nginx/backup/backend.qbox.sa.20261007-0329.bak`. The password is in
    `/root/qbox-ops/secrets/nginx-emqx-basic-auth.txt`.
- **IP allowlist:** waiting for the owner's IP. The logs suggest `103.229.253.64/27`.

**Device commands:** the backend does not use the EMQX management API (`EMQX_SYNC_MODE=postgresql`); commands
travel over MQTT with separate credentials.
- The backend's MQTT publisher and consumer are connected to EMQX after the change.
- **No locker is online** (last contact: `ELF-484` on 3 Oct), so "a command reaches a locker" could not be tested.
  Re-check when a locker connects.

## 2. DEBUG off (step 1) — done, 03:30 UTC

Steps:
- Backup `qbox-db-20261007-0329-c384f7c3.dump` (17 MB).
- Env backup at `/root/backups/env.development.20261007-0327*`; `.env.development` is now `chmod 600`.
- Set `DEBUG=false`, then recreated web, websocket, worker, beat and both MQTT services (28 s, no rebuild).

Verified:
- Django reports `DEBUG=False` in web and worker.
- `/health/live/` and `/health/ready/` return 200.
- Static `admin/css/base.css` returns 200 (served by nginx), and `/api/docs/` returns 200.
- An unknown URL returns a plain 404 with no debug page. Before, it listed every URL pattern.
- The portal page `/d/FFK-262` returns 200.
- A wrong login returns a clean JSON 401.
- The 15-minute log watch (03:31–03:46 UTC):
  - worker, beat, websocket and both MQTT services: 0 errors;
  - 212 background tasks OK, 0 failed;
  - web: 0 errors outside 03:32–03:33. That minute was my own probing of the old panel routes, which sent about
    156 deliberately wrong requests;
  - `/health/ready/` 200.

**Rollback:** set `DEBUG=true` in `.env.development`, then
`docker compose -f docker-compose.development.yml up -d --no-deps --force-recreate web websocket worker beat mqtt-consumer mqtt-publisher`.

Found while checking (pre-existing, not caused by DEBUG; needs a code fix):
- **`MEDIA_ROOT` is the folder of the `media` Django app.** So the app's source files are downloadable at `/media/…`
  and `/api/media/…`.
- **Uploaded ID cards** (`media/id_cards/`) are served at public URLs without login. The names are random, but the
  files are not protected.
- Proposed fix: move uploads out of the app folder and serve private documents through signed, expiring links.

## 3. test.qbox.sa and the August panels — analysis (nothing changed)

**(a) Routes the deployed bundles call** (each probed against the current backend with the exact path):

| Panel (built) | Routes | Exist (401/403/405/200) | Retired (410) | Not found (404)* | Error |
|---|---|---|---|---|---|
| super-admin (17 Aug) | 50 | 19 | 4: `/driver/…`, `/shipments/statuses/` | 27 | — |
| merchant (2 Aug) | 50 | 22 | 2: `/shipments/create/`, `/shipments/statuses/` | 25 | `/warehouses/lookup/` → **500** |
| service-provider (5 Aug) | 56 | 24 | 10: drivers, payouts, dashboard | 22 | — |

\* Some 404s are prefixes the panel completes at runtime. Others are routes removed with the legacy
driver / service-provider / finance code.

- Core merchant functions (create a shipment, statuses) are retired.
- The service-provider role no longer exists.

**(b) Real use:**
- **merchant.qbox.sa** (logs 19 Sep – 7 Oct): no real use. The bursts on 21 and 28 Sep come from cloud scanners
  (`34.187.219.231`); the owner's network appears twice.
- **service-provider.qbox.sa** (23 Sep – 7 Oct): no real use.
- **super-admin.qbox.sa:** its traffic shares the main log, which has no host field. Requests referred from it (since
  23 Sep) came only from the same scanner and the VPS itself.
- nginx keeps about 14–19 days, not 30.

**Recommendation: leave `test.qbox.sa` as it is until the new panels ship.** Pointing it at the backend would take a
certificate, ALLOWED_HOSTS and CORS changes, and would still not make the August panels work: their core routes are
retired. Optionally replace the three old `dist/` folders with a one-page "new panel coming" notice. Separately, the
`/warehouses/lookup/` 500 is a backend bug to fix in a code batch.

## 5. What the public installation-QR key allows today

The installation QR (AES-GCM, `QR_SECRET_KEY_B64`) holds `device_id`, `device_uid`, a nonce and a timestamp. With
the public default key, anyone can:
- **read** any photographed installation label: it reveals the device's internal identifiers. They are not secrets
  and grant no access on their own.
- **forge** a label for any device whose UID they know.

Forging gains little today. Only two features accept these tokens, both behind staff login: the technician
installation step "device identity" (which also accepts the UID typed in plain text) and the factory "Check a
printed QR" tool. Lockers do not use this key to authenticate (they use certificates), door codes use a different key,
and no customer-facing endpoint accepts it.

Fallback-key support is in commit `474ea56a` (local, not pushed). Rotate the key, keep the public key as a fallback
only until the 2 installed labels are reprinted, then remove it. The safety check flags it while it is still listed.
