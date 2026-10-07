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

## Off-server copy — Backblaze B2 (owner decision 2026-10-07)

Status: **waiting for the bucket and an application key limited to it** (owner creates them).
Plan once they exist:
- `rclone` on the VPS with a `b2` remote (bucket-scoped key) wrapped in an `rclone crypt` remote. File contents and
  names are encrypted on the VPS before upload; Backblaze only ever sees ciphertext.
- The crypt **password and salt** are generated once and given to the owner once to keep in the password manager. On
  the VPS they exist only inside root's `rclone.conf` (`600`). Losing them makes the off-site copies unreadable: they
  are the only thing that must survive a total loss of the VPS.
- After every daily run: `rclone copy /root/backups/daily b2crypt:daily` plus a weekly `rclone check`. Bucket lifecycle
  rule: keep 30 days of file versions.

## Restore when the VPS is gone

You need: a new server with Docker, the Git repository, the Backblaze bucket name + key, and the crypt password +
salt from the password manager.
1. Install `rclone` and recreate the two remotes (`rclone config`): `b2` (account id + application key) and `b2crypt`
   (type crypt, remote `b2:<bucket>`, the same password and salt).
2. `rclone copy b2crypt:daily ./restore --max-age 48h` and `sha256sum -c qbox-*.sha256`.
3. Clone the backend, put back `.env.development` (rebuild it from the password manager / rotate every secret: a
   lost server means the old secrets must be treated as exposed), start only `db`:
   `docker compose -f docker-compose.development.yml up -d db`.
4. `docker exec -i qbox-development-db pg_restore -U <user> -d qbox_development --no-owner < restore/qbox-db-….dump`
5. Start everything with `./deploy.sh` (it runs migrations: there should be none pending), restore files from
   `qbox-files-….tar.gz` into the MinIO volume and `media/`, point DNS to the new server, check `/health/ready/`.

## Off-server copy — options considered

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

## Retention of the old project dumps (owner decision 2026-10-07)

`smart_locker_postgres_data-20261007.sql.gz` (old `qbox_db`, 103 tables) and the empty
`smartlocker_postgres_data-20261007.sql.gz`: **keep 90 days, delete on 2027-01-05**.
- VPS: automatic, `/etc/cron.d/qbox-old-dump-expiry` deletes them on or after 2027-01-05.
- This machine: **delete `~/qbox-backups/old-dbs/smart_locker_*` and `smartlocker_*` by hand on 2027-01-05.**
