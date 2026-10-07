# Switching DEBUG off on the VPS — analysis and step plan (2026-10-07)

Today: `DEBUG=true`, `DJANGO_ENV=development`, `QBOX_REAL_CUSTOMER_DATA` not set. DEBUG comes from
`/var/www/Qbox-Back-End/.env.development` (not in git; currently **world-readable `644`** — it holds every secret;
make it `600`). `DJANGO_ENV=development` is also hard-coded in `docker-compose.development.yml` (`environment:`).

## (a) What changes between DJANGO_ENV=development and production

| Area | development (today) | production |
|---|---|---|
| DEBUG | from env (`true` today) | always off; refuses to start if `DEBUG=true` |
| QBOX_REAL_CUSTOMER_DATA | from env (unset) | always on |
| ALLOWED_HOSTS / CORS / SITE_URL | env, with development defaults (localhost ports, backend/dev/super-admin/merchant) | env **required**, no defaults |
| SECRET_KEY, QR_SECRET_KEY_B64 | insecure defaults allowed | required (startup error if missing) |
| QBOX_STICKER_SIGNING_KEYS | falls back to a SECRET_KEY-derived key | required to print stickers |
| Cookies | secure flags from env (already `true`) | secure forced, `SameSite=None` |
| HTTPS redirect, HSTS | from env (`SECURE_SSL_REDIRECT=false`, HSTS 0) | redirect default on; HSTS 30 days + subdomains + preload unless env says otherwise |
| Email, FCM push | console / optional | SMTP and FCM credentials required (FCM on by default) |
| MinIO, Celery broker/result, MQTT credentials, Moyasar webhook secret, stream host | defaults allowed | required |
| MQTT TLS | from env | TLS on and no insecure fallback by default |
| Device onboarding | unknown devices auto-created | **no auto-create, bootstrap secret required** — changes how new lockers register (hardware team must know) |
| Logging | development format | production format |

## (b) Static and media files with DEBUG off

- **Static** (`/static/`): with DEBUG off Django stops serving it; **nginx already serves it** from
  `/var/www/Qbox-Back-End/staticfiles/` (`deploy.sh` runs collectstatic and copies it there). Checked: `/static/admin/css/base.css` → 200 via nginx.
- **Media** (`/media/`, `/api/media/`): served by Django through explicit URL routes that do not depend on DEBUG;
  nginx also serves `/media/qbox_images/` and `/media/package_qrcodes/` directly. No change.
- Swagger / ReDoc load their assets from a CDN — no change.

## (c) Hosts and origins

| Domain | Resolves to VPS | TLS | In ALLOWED_HOSTS | In CSRF/CORS | Used by |
|---|---|---|---|---|---|
| backend.qbox.sa | yes | yes | yes | yes | API, driver portal |
| dev.qbox.sa | **no DNS** | — | yes | yes | nothing today (can stay or be removed) |
| test.qbox.sa | yes | **no certificate on this server** | **no** | no | **the deployed super-admin and merchant panels (built Aug 2026) call it — their API calls fail (400)** |
| super-admin / merchant / service-provider.qbox.sa | yes | yes | n/a (static sites) | yes | panels |
| factory.qbox.sa | yes | **HTTP only** | n/a | no | inspection portal (port 3001) |
| localhost:3000 / 5173 / 8000 | — | — | localhost yes | yes | developer machines — remove from production lists later |

DEBUG does not change host checks (ALLOWED_HOSTS is already enforced). The `test.qbox.sa` problem is separate and exists today:
either point the panels at `backend.qbox.sa` (rebuild them) or add `test.qbox.sa` to nginx (certificate) and ALLOWED_HOSTS.

## (d) Anything else that would break with DEBUG=False

Nothing found:
- error pages become generic (API errors are JSON either way);
- Django stops keeping every SQL query in memory — less memory use in the long-running worker;
- the `qbox.E001` system check only applies once `QBOX_REAL_CUSTOMER_DATA=true`.
Login, OTP, portal, Swagger and static assets do not depend on DEBUG.

## Step 1 — DEBUG off (only this)

1. Backup: run `/root/qbox-ops/backup-daily.sh` and confirm the `ok` line in `/var/log/qbox-backup.log`.
2. `cd /var/www/Qbox-Back-End && cp -p .env.development /root/backups/env.development.$(date -u +%Y%m%d-%H%M) && chmod 600 .env.development`
3. Edit `.env.development`: `DEBUG=false`.
4. Recreate the app containers (no rebuild, ~1–2 min):
   `docker compose -f docker-compose.development.yml up -d --no-deps --force-recreate web websocket worker beat mqtt-consumer mqtt-publisher`
5. Verify:
   - `docker exec qbox-development-web printenv DEBUG` → `false`
   - `/health/live/` and `/health/ready/` → 200
   - `https://backend.qbox.sa/static/admin/css/base.css` → 200
   - `https://backend.qbox.sa/api/docs/` → loads
   - `https://backend.qbox.sa/does-not-exist/` → plain 404 page, **no yellow Django debug page**
   - one owner login and one portal page `/d/<qbox_code>` work
   - web / worker logs clean for 15 minutes
6. **Rollback** (1 minute): set `DEBUG=true` in `.env.development` and repeat step 4.

`deploy.sh` never touches `.env.development`, so the change survives deploys.

## Step 2 — later, separately: QBOX_REAL_CUSTOMER_DATA=true

Turns on the production-grade transport rules and makes `DEBUG=true` impossible (settings + system check). The env file
already pins `SECURE_SSL_REDIRECT=false`, `SECURE_HSTS_SECONDS=0`, `SECURE_HSTS_INCLUDE_SUBDOMAINS=false`,
`SECURE_HSTS_PRELOAD=false` — **keep them that way** until every `*.qbox.sa` site has HTTPS: HSTS with subdomains would
make browsers refuse `http://factory.qbox.sa`, and preload is very hard to undo.
- Do: add `QBOX_REAL_CUSTOMER_DATA=true`, recreate the same containers, verify as in step 1.
- **Rollback:** remove the line and recreate.

## Step 3 — later still: DJANGO_ENV=production

Needs a repo change (compose hard-codes `development`) and every required value from table (a). Two things need a
decision first: new-device onboarding rules (hardware team) and FCM / SMTP credentials. Recommendation: stay on
`development` + `QBOX_REAL_CUSTOMER_DATA=true` (the documented design for this VPS) until those are settled.

## Startup check (in batch `99bb9edf`, not pushed yet)

`QBOX_ENFORCE_RUNTIME_SAFETY=true` makes the processes refuse to start with DEBUG on or default / weak / missing secrets
(names only in the error). Off by default, so it cannot block a deploy. Before switching it on, run
`docker exec qbox-development-web python manage.py qbox_check_secrets`: it lists the same findings without
blocking anything. Expected findings today: DEBUG on, SECRET_KEY too short, QR key = public default, sticker key not set.
