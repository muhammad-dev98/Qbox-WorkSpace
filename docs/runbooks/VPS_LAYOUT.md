# VPS layout — what lives where (Hostinger srv1117845, 69.62.125.223) — 2026-10-07

Ubuntu, 2 vCPU (Hostinger CPU cap: sustained load shows as CPU steal — never run tests here), 96 GB disk.

## Applications

| Path | What | How it runs |
|---|---|---|
| `/var/www/Qbox-Back-End` | Backend repo = exactly `origin/main`; `git status` empty | Docker compose project `qbox-development` (`docker-compose.development.yml`), deployed by `deploy.sh` (see `Qbox-Backend/docs/runbooks/DEPLOY.md`) |
| `/var/www/Qbox-Back-End/.env.development` | All runtime secrets and settings (`chmod 600`, not in git) | read by compose |
| `/var/www/Qbox-Back-End/uploads`, `private_media`, `media/` (data only) | Uploaded files (public / private) and the old media data | bind mounts; **removed when R2 replaces them** |
| `/var/www/qbox-static` | Django static files (collectstatic output, written by `deploy.sh`) | served by nginx `/static/` |
| `/var/www/Qbox-Merchant-panel`, `Qbox-Super-Admin`, `Qbox-Service-Provider` | August panel builds (`dist/`) | nginx static sites; kept until the owner decides |
| `/var/www/qbox-inspection-portal` | Factory inspection portal (Next.js) | PM2 `inspection-portal`, port 3001, `factory.qbox.sa` (HTTP) |
| `/opt/qbox-relay-agent` | Camera relay enrollment agent | systemd `qbox-relay-agent` (port 19100 on the docker bridge) |
| — | Media relay bridge | systemd `qbox-media-relay-bridge` (socat 172.17.0.1:18889 → 127.0.0.1:18889) |
| — | TURN server for video | systemd `coturn`, port 3478 |
| — | Tailscale | systemd `tailscaled` |

## Containers (`qbox-development`)

db (PostgreSQL 16, 127.0.0.1:15432), redis (16379), rabbitmq, minio (19000/19001 — **removed in the R2 item**), emqx
(MQTT TLS **8883 public**), web (127.0.0.1:18080), websocket (18081), worker, beat, mqtt-consumer, mqtt-publisher,
mediamtx (RTSP 8554 public). One-shots per deploy: migrate, mqtt-bootstrap, emqx-init.
Volumes: `qbox-development_*` (postgres, redis, rabbitmq, minio, emqx-certs, emqx-data, emqx-log).

## nginx (`/etc/nginx/sites-enabled`)

`backend.qbox.sa` (API, `/static/` → `/var/www/qbox-static`, `/media/` → `uploads/` with private paths denied, EMQX
dashboard behind basic auth), `merchant.` / `super-admin.` / `service-provider.qbox.sa` (old panels),
`factory.qbox.sa`. Device CA copy for mTLS: `/etc/nginx/qbox-certs/device-ca.crt`. Config backups before each change:
`/etc/nginx/backup/<site>.<UTC stamp>.bak`.

## Operations (`/root/qbox-ops`, `chmod 700`)

| Item | Purpose |
|---|---|
| `backup-daily.sh` | Nightly backup 23:30 UTC (`/etc/cron.d/qbox-backup`): pg_dump + MinIO/media/uploads/private_media tar → `/root/backups/daily`, 14 days. Also run by `deploy.sh` before migrations. |
| `archive-app-logs.sh` | Nightly 00:10 UTC (`/etc/cron.d/qbox-app-logs`): last 24 h of every container log → `/var/log/qbox/<service>-<day>.log.gz`, 90 days |
| `secrets/` | Root-only secrets (EMQX dashboard, nginx basic auth, `r2.env`) — never printed |
| `archive/` | Root-only archives of removed files (old certificates, scripts, CI leftovers, nginx backups) |

## Backups (`/root/backups`, `chmod 700`)

`daily/` (14 days), `old-dbs/` (old smart_locker dump, deleted 2027-01-05 by `/etc/cron.d/qbox-old-dump-expiry`),
`old-code/` (archived stage folders, deleted 2027-01-05 by `/etc/cron.d/qbox-old-code-expiry`; copies on the
development machine), `env.development.*` (env copies before changes). Off-site encrypted copies to R2: R2 item.

## Logs

| Log | Retention |
|---|---|
| nginx `/var/log/nginx/*.log` | daily, compressed, 90 days (`/etc/logrotate.d/nginx`) |
| app containers | Docker keeps 3 × 10 MB per container; daily archive 90 days in `/var/log/qbox/` |
| `/var/log/qbox-deploy.log` (one line per deploy), `/var/log/qbox-backup.log` | monthly, compressed, 12 months (`/etc/logrotate.d/qbox`) |

## Housekeeping crons

`docker-image-prune` (daily: unused images older than 24 h), `docker-builder-prune` (weekly: build cache older than
7 days), `certbot` (certificate renewal).
