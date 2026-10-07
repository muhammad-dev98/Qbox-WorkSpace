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

---

# Part 3 — owner decisions of 7 Oct (round 3)

## 1. Private files ("ID card exposure")

**Correction to part 2:** there are **no ID cards on the VPS**. `media/id_cards/` exists only on a developer machine.
What the VPS really served publicly from the `media` app folder:
- `media/merchant/business-documents/`: **6 PDFs** (commercial registration, tax certificate, national address of
  merchant applications);
- `media/media_uploads/`: 55 photos;
- the `media` app's source code (`*.py`, `migrations/`).

**Blocked now** (nginx `deny all`, regex locations for both `/media/` and `/api/media/`, covering `id_cards`,
`merchant/business-documents`, `media_uploads`, `migrations`, `__pycache__`, `*.py`):
- `nginx -t` OK; backup `/etc/nginx/backup/backend.qbox.sa.20261007-0402.bak`.
- Verified: 403 on both prefixes for each blocked path; normal media (`qbox_images`, `qrcodes`) still 200.

**Who downloaded them:** nginx logs cover 23 Sep – 7 Oct (all retained). The only requests to these paths are my
own 3 checks from `103.229.253.77`. **No download from outside `103.229.253.64/27`.** Before 23 Sep it cannot be
checked (logs rotated away).

**Found while fixing:**
- **Anyone could submit or replace a merchant's business documents** without login
  (`merchant_business_documents_by_id`, by merchant ID). It is still open; it is part of the application flow before the
  merchant has a login, so closing it is a product decision. Proposal: require the applicant's OTP session or a one-time
  link. With the batch, the endpoint no longer returns download links to anonymous callers.
- **Uploads were never persisted:** the containers had no media volume, so anything uploaded at runtime was lost on
  every deploy. The images contained the host `media/` folder through `COPY .`. Only 1 file reference in the DB, so
  little was lost.

**Code batch (local main, tested, not pushed):** private storage and signed links for the business documents;
`MEDIA_ROOT` → `uploads/` (bind mount, survives deploys); `/warehouses/lookup/` fixed (login required, own
warehouses only, no 500); tests use temporary media folders. Deploy steps and rollback:
`docs/runbooks/PRIVATE_FILES_DEPLOY.md`. `backup-daily.sh` now also tars `uploads/` and `private_media/` once they exist.

## 2. Lockers offline since 3 October

| Device | What it is | Last seen |
|---|---|---|
| `ELF-484` | **The only physical locker.** Real certificate (valid to 2027-09-19). Assigned to a merchant account with the reason "ELF-484-merchant-test"; installation completed 21 Sep. Not a paying customer. | 3 Oct 15:24 UTC |
| `QBT001`, `QBT002` | Test records on homeowner accounts | — |
| `FFK-262`, `ZVD-337` | Test records, never connected (their installation orders show COMPLETED on 27 Sep — test data) | never |
| `QBOX-TEARDOWN-CHECK-01` | Factory unit | — |

**No locker is installed at a real customer.**

Why `ELF-484` is offline, server side checked:
- It went silent on 3 Oct 15:24 UTC. **No deploy, restart or config change happened between 2 Oct and 5 Oct 01:47**,
  so nothing on the server changed at that moment.
- EMQX since its restart on 5 Oct: **no connection attempt from any locker, no TLS or authentication error**. A locker
  that tried with a bad certificate or password would show up there.
- Port 8883 is reachable from outside. The server certificate (reissued 5 Oct) chains to the **unchanged CA** (since
  4 Sep) and names `backend.qbox.sa`; a TLS handshake verifies OK.
- Today's EMQX change only touched the dashboard (password, basic auth in nginx); MQTT listeners and device
  credentials are unchanged. The backend's own MQTT clients connect fine.

**Conclusion: the locker is not reaching the server at all** — power, network/SIM, or the device itself.
The 5 Oct rebuild cannot be the cause (it came 2 days later). Someone needs to look at the unit: is it powered, does
it have network, what does its local log say. No device-side settings were changed.

## 3. IP allowlist — skipped, basic auth stays.

## 4. Old panels — notice page prepared, not applied

`docs/runbooks/OLD_PANELS_NOTICE.md`: one static bilingual page, the nginx `root` swap for merchant, super-admin and
service-provider, verification and a 1-minute rollback. Replace the support contact before applying.

---

# Part 4 — deploy of `27d6e005` (7 Oct, 06:26 UTC push by the owner)

- Deploy run https://github.com/Hegmon-2/Qbox-Back-End/actions/runs/37581474919 — success. Deployed commit =
  `origin/main` = `27d6e005`. Backup before: `qbox-db-20261007-0602-c384f7c3.dump` (17.7 MB).
- Rule 4: `/health/live/` and `/health/ready/` 200; 0 pending migrations (`shipping 0009`, `accounts 0013` applied);
  all containers up/healthy; `DEBUG=False`; `MEDIA_ROOT=/app/uploads`, `QBOX_PRIVATE_MEDIA_ROOT=/app/private_media`.
- Smoke: forged private-file link 401 (anonymous); `/warehouses/lookup/` 401 without login (was 500); portal
  `/d/FFK-262` 200; static 200; `/api/docs/` 200; wrong login clean 401.
- `PRIVATE_FILES_DEPLOY.md` step 3 done 06:39 UTC: nginx `/media/` aliases → `uploads/` (backup
  `backend.qbox.sa.20261007-0639.bak`). `/media/models.py`, `/media/__init__.py`, business-document paths → 403;
  `/media/qrcodes/…`, `/media/install-….jpg` → 200.

## Correction: what was actually exposed

Checked against the database after the deploy:
- **The 6 "business document" PDFs are test fixtures** (12–19 bytes, text like `%PDF-1.4 commercial…`, all dated
  18 Sep — the test runs that were still executed on the VPS then). **No `MerchantBusinessDocuments` row exists in
  production.**
- **The 55 evidence files are test fixtures too** (`photo.jpg` 132 bytes, `handover.jpg` 68 bytes, all 18 Sep).
- **So no real customer document or photo was ever publicly exposed.** The only real evidence row (installation
  photo, 22 Sep) points to a file that no longer exists: it was lost when containers were recreated, because runtime
  uploads were not persisted before this deploy.

---

# Part 5 — merchant data exposure (found 2026-10-07 09:45 UTC while mapping merchant onboarding)

- **`GET /auth/merchant/accounts` and `/api/v1/merchants/accounts/` were public** (no login) and returned, for all
  **4 merchant accounts**: IBAN, account number, account holder, owner email and phone. nginx logs (14 days): no
  request other than my two checks. **Closed in nginx 09:47 UTC** (404; backup `backend.qbox.sa.20261007-0947.bak`).
- **Public merchant directory** (`/auth/merchants/public`, `/auth/merchant/<id>/public`) returned owner email and
  phone for every merchant, pending ones included. No caller in the logs except my checks. Closed in nginx too.
- **`POST /auth/merchant/store/create`** let any logged-in user overwrite any merchant's store and bank details
  (user id from the request body). Not reachable anonymously; no exploitation evidence available (POST bodies are
  not logged).
- Code fix `76d20cb0` (merchant list super-admin only; directory = approved merchants, business fields only; store
  create = own account or super admin). After it is deployed the nginx blocks can stay (no caller) or be removed.
- Earlier the same day: CORS allowed any `*.ngrok-free.app` origin with credentials (fix `bcd69672`) and localhost
  origins on the VPS (fix `41680a23` + `CORS_ORIGINS_EXACT=true`).
