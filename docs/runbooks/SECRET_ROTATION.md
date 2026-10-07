# Secret rotation — preparation and checklist (2026-10-07)

All values live in `/var/www/Qbox-Back-End/.env.development` on the VPS (not in git; make it `chmod 600`).
After editing it, "recreate apps" means:
`docker compose -f docker-compose.development.yml up -d --no-deps --force-recreate web websocket worker beat mqtt-consumer mqtt-publisher`
(no rebuild). Generate values with `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` unless noted.

**Prerequisite:** batch `99bb9edf` must be live (it adds `SECRET_KEY_FALLBACKS` everywhere, `JWT_SIGNING_KEY`, and
`manage.py qbox_check_secrets`). Do not rotate SECRET_KEY before that deploy, or every user is logged out and door codes,
OTPs and pending device commands break.

## What depends on SECRET_KEY today (verified in the code)

| Use | Survives rotation with `SECRET_KEY_FALLBACKS`? |
|---|---|
| Django sessions, password-reset and email-verification tokens | yes (Django built-in) |
| Signed links: recipient tokens (`shipments/services/access.py`), label download links (`shipping/api/views.py`) | yes (Django signing) |
| Door-code digests (`shipments/services/locker_portal.py`) | yes, after `99bb9edf` |
| OTP encryption (`verification/services/helpers.py`) | yes, after `99bb9edf` |
| Device command secrets (`hardware_devices/services/command_secret_crypto.py`) | yes, after `99bb9edf` |
| **Login tokens (JWT, 1 day access / 7 days refresh)** | **no** — simplejwt ignores fallbacks. After `99bb9edf` they use `JWT_SIGNING_KEY` (default = SECRET_KEY). Pin it before rotating. |
| **Identity sticker signatures** | today **derived from SECRET_KEY** (`QBOX_STICKER_SIGNING_KEYS` is not set). No sticker has been printed yet (no audit events), so setting a dedicated key now costs nothing. |

**Separate keys (confirmed):**
- **Payment-token encryption** (`PAYMENT_TOKEN_ENCRYPTION_KEYS`) is separate from SECRET_KEY, but it is **not set**, so no
  card tokens are stored today.
- **Installation-QR encryption** (`QR_SECRET_KEY_B64`) is separate, but it is **the public development default from the
  source code**.

## Findings today

- **SECRET_KEY:** 10 characters (should be ≥ 50).
- **QR_SECRET_KEY_B64:** the public default.
- **EMQX_DASHBOARD_PASSWORD:** 4 characters.
- **QBOX_STICKER_SIGNING_KEYS, PAYMENT_TOKEN_ENCRYPTION_KEYS, JWT_SIGNING_KEY, SECRET_KEY_FALLBACKS:** not set.
- **Old git history of `.env.prod`:** contains SECRET_KEY, Moyasar secret and webhook secret, WhatsApp token, SPL key and
  EMQX dashboard password.

## Checklist (in this order)

| # | Secret | Where to rotate | Env var(s) | Restart | Verify |
|---|---|---|---|---|---|
| 1 | Sticker key (new) | — | `QBOX_STICKER_SIGNING_KEYS=<new>` | recreate apps | factory panel: print one sticker, scan it → portal shows no warning |
| 2 | Pin login tokens | — | `JWT_SIGNING_KEY=<current SECRET_KEY value>` | recreate apps | you stay logged in |
| 3 | SECRET_KEY | — | `SECRET_KEY=<new 64+ chars>`, `SECRET_KEY_FALLBACKS=<old value>` | recreate apps | log in/out, request an OTP, open a door with a code issued before the change, `qbox_check_secrets` no longer lists SECRET_KEY |
| 4 | Remove fallback (after 7 days) | — | delete `SECRET_KEY_FALLBACKS` | recreate apps | nothing breaks |
| 5 | JWT key (optional, quiet hour) | — | `JWT_SIGNING_KEY=<new>` | recreate apps | **everyone must log in again** — announce first |
| 6 | Moyasar secret key | Moyasar dashboard → API keys (live) | `MOYASAR_SECRET_KEY` | recreate apps | a real small payment + refund in the app, or Moyasar test mode first |
| 7 | Moyasar webhook secret | Moyasar dashboard → Webhooks (each webhook) | `MOYASAR_WEBHOOK_SECRET` | recreate apps | Moyasar webhook log shows 200 for the next event |
| 8 | WhatsApp token | Meta Business → System users → generate token | `WHATSAPP_TOKEN` | recreate apps | request an OTP by WhatsApp |
| 9 | SPL key | SPL developer portal | `SPL_API_KEY` | recreate apps | `/api/v1/addresses/lookup?…` returns an address |
| 10 | EMQX dashboard password | EMQX dashboard → users (admin) | `EMQX_DASHBOARD_PASSWORD` (and `EMQX_MANAGEMENT_API_PASSWORD` if it is the same user) | `emqx` container + apps | dashboard login; backend device commands still reach a locker |
| 11 | QR key (installation labels) | — | `QR_SECRET_KEY_B64=<new 32-byte base64>` (`python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`) | recreate apps | the installation QR labels already printed in **2 installed units** stop decrypting: reprint them, or ask for fallback-key support in a next batch first |
| 12 | Payment-token key (new) | — | `PAYMENT_TOKEN_ENCRYPTION_KEYS=<Fernet key>` (`python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`) | recreate apps | only needed once saved cards go live |
| 13 | MinIO credentials (optional) | `mc admin user` / MinIO console | `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | `minio` + apps | label download works |
| 14 | Final check | — | `QBOX_ENFORCE_RUNTIME_SAFETY=true` once `qbox_check_secrets` reports nothing | recreate apps | services start; `/health/ready/` 200 |

Keep each old value for a day in a root-only file on the VPS (`/root/backups/env.development.<timestamp>`) so a rotation
can be rolled back by restoring the env file and recreating the apps. Git history still contains the old values; after
rotation they are useless. Purging history is a separate decision.

## Database password (PostgreSQL role `qbox_development`) — quiet hour, ~10 minutes

Why: copies of the password sat in old CI env files on the VPS (root-only, deleted 2026-10-07). Rotate it once.

Who uses it (`docker-compose.development.yml`, all from `.env.development`): web, websocket, worker, beat,
mqtt-consumer, mqtt-publisher, the one-shots migrate / mqtt-bootstrap, and **EMQX** (device and backend MQTT logins
are checked against PostgreSQL, so EMQX must get the new value too). The `db` container itself does not need a restart:
`POSTGRES_PASSWORD` is only read when the database is first created. The nightly backup uses the container's local
socket and is not affected.

1. **Backup**: `/root/qbox-ops/backup-daily.sh` and
   `cp -p /var/www/Qbox-Back-End/.env.development /root/backups/env.development.$(date -u +%Y%m%d-%H%M)`.
2. **New password** (hex only — no quoting problems in the env file or the EMQX config):
   `openssl rand -hex 32` — keep it in your password manager; do not paste it into a chat.
3. **Change it in PostgreSQL** (interactive, so it never lands in shell history):
   `docker exec -it qbox-development-db psql -U qbox_development -d qbox_development` → `\password qbox_development`
   → enter the new value twice → `\q`. Connections that are already open keep working; new ones need the new value.
4. **Change it in `.env.development`** (both keys hold the same value): `DB_PASSWORD=<new>` and
   `POSTGRES_PASSWORD=<new>`.
5. **Recreate everything that connects** (about 1 minute; lockers reconnect to MQTT on their own):
   `cd /var/www/Qbox-Back-End && docker compose -f docker-compose.development.yml up -d --no-deps --force-recreate emqx web websocket worker beat mqtt-consumer mqtt-publisher`
6. **Verify**:
   - `curl -s -o /dev/null -w '%{http_code}' https://backend.qbox.sa/health/ready/` → `200`;
   - `docker logs --since 10m qbox-development-db 2>&1 | grep -c 'password authentication failed'` → `0`;
   - `docker ps` shows mqtt-consumer / mqtt-publisher / web `healthy`;
   - `docker logs --since 10m qbox-development-emqx 2>&1 | grep -ci 'authentication.*fail\|bad_username_or_password'` → `0`;
   - `docker logs --since 10m qbox-development-worker 2>&1 | grep -c 'succeeded in'` > 0;
   - the next deploy (or `docker compose ... run --rm migrate`) connects without errors.
7. **Rollback** (if anything fails to connect): put the old value back in PostgreSQL (`\password` as in step 3, with
   the value from the env backup), restore the env file (`cp -p /root/backups/env.development.<stamp>
   /var/www/Qbox-Back-End/.env.development`), repeat step 5.
8. After a day without problems: delete the env backup from step 1 (it holds the old password).
