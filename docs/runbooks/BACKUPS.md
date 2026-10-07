# Production backups (set up 2026-10-07)

## What runs

| Item | Detail |
|---|---|
| Schedule | Every day 02:30 Asia/Riyadh (23:30 UTC), `/etc/cron.d/qbox-backup` on the VPS |
| Script | `/root/qbox-ops/backup-daily.sh` (low CPU / IO priority) |
| Database | `pg_dump` of `qbox_development`, custom format, compressed: `qbox-db-<UTC date-time>-<commit>.dump` (~18 MB) |
| Files | MinIO data volume + `/var/www/Qbox-Back-End/media`: `qbox-files-<UTC date-time>.tar.gz` (~24 KB today) |
| Checks | the dump must be readable by `pg_restore --list` before it is kept; SHA-256 checksums per run (`qbox-<stamp>.sha256`) |
| Where | `/root/backups/daily/` (root only, `700`) |
| Retention | 14 days (older files deleted by the script) |
| Log | `/var/log/qbox-backup.log` — one line per run: `ok db=… files=… kept=N` |

First run 2026-10-07 02:27 UTC: 26 s, 18 MB database dump, 24 KB files.

## Off-server copy — decision needed

A backup that only lives on the VPS is lost with the VPS. Options:

| Option | Cost | Effort | Notes |
|---|---|---|---|
| **A. Backblaze B2 private bucket** (recommended) | ~USD 0.006 / GB / month; our data ≈ 0.4 GB for 14 days | You create the bucket and an application key limited to that bucket; I add `rclone` upload to the script | Encrypted upload (rclone crypt). Survives a VPS loss. |
| B. AWS S3 / Hostinger Object Storage | similar | same | |
| C. Pull to the office machine | free | a scheduled `rsync` on this machine | Only works while the machine is on; fine as a second copy, weak as the only one. |

Today a manual copy was pulled to this machine: `~/qbox-backups/` (checksums verified).

## Restore test (2026-10-07)

Restored `qbox-db-20261007-0227-c384f7c3.dump` into a throwaway PostgreSQL 16 on this machine (not the VPS):

- `pg_restore --exit-on-error`: no errors, 39 s.
- 209 tables, 231 migrations; **row counts of all 209 tables identical to production** (206,443 rows), checked table by table.
- File archive readable (120 entries). The throwaway database was deleted afterwards.

## How to restore (production)

1. Stop writers: `docker compose -f docker-compose.development.yml stop web websocket worker beat mqtt-consumer`.
2. Take a fresh dump of the current state first (even if it is broken).
3. `docker exec -i qbox-development-db pg_restore -U <user> -d qbox_development --clean --if-exists --no-owner < qbox-db-….dump`
4. Files: `tar -xzf qbox-files-….tar.gz` into the MinIO volume (`_data`) and `/var/www/Qbox-Back-End/media`.
5. Start the services again; check `/health/ready/` and `manage.py showmigrations`.

## Other copies kept

`/root/backups/20261005-0650-cda3b693.sql.gz` (manual, before the Phase 5 deploy) and `/root/backups/old-dbs/`
(old `smart_locker` database `qbox_db` — 103 tables; the empty `smartlocker` cluster; the dropped
`qbox_development_test`), all also copied to `~/qbox-backups/old-dbs/` with verified checksums.
