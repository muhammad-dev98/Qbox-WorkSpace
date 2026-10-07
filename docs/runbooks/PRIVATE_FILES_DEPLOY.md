# Deploying the private-files batch (uploads out of the code folder) — 2026-10-07

What the batch changes (Qbox-Backend):
- `MEDIA_ROOT` default `media` → `uploads` (`BASE_DIR/uploads`, `/app/uploads` in Docker). The `media/` folder is the
  `media` Django app's source code and must never be served again.
- Merchant business documents (commercial registration, tax certificate, national address) are stored in
  `QBOX_PRIVATE_MEDIA_ROOT` (`/app/private_media`) and only downloadable through
  `/api/v1/files/private/<token>/`: a link issued to one logged-in user, valid `QBOX_PRIVATE_FILE_LINK_TTL_SECONDS`
  (default 300 s), re-checked at download (owner or back office), audited (`private_file.downloaded`).
- `docker-compose.development.yml` bind-mounts `./uploads` and `./private_media` into web, websocket, worker and
  mqtt-consumer — **uploads now survive container recreation** (before, every deploy lost runtime uploads).
- `deploy.sh` creates both folders (owner `10001`, `uploads` 755, `private_media` 750).
- Migration `accounts 0013`: AlterField only (storage), no SQL change.
- `/warehouses/lookup/` (and `/api/v1/…`) now needs login; merchants see their own warehouses, back office all. (Was public and returned 500.)

Paths below: `APP=/var/www/Qbox-Back-End`.

## 1. Before the push (owner pushes after this) — DONE 2026-10-07 06:05 UTC

Result: backup `qbox-db-20261007-0602-c384f7c3.dump` (17.7 MB, checksums OK); `uploads/` 60 files (no `.py`),
`private_media/` 6 files. `deploy.sh` uses `git reset --hard`, which leaves the untracked folders alone.

Copy, don't move — the live containers still read `media/` until the deploy finishes.

```sh
cd /var/www/Qbox-Back-End
/root/qbox-ops/backup-daily.sh && tail -1 /var/log/qbox-backup.log         # expect "ok", note size
mkdir -p uploads private_media
# public uploads: everything in media/ except the app's code and the private documents
rsync -a --exclude='*.py' --exclude='__pycache__/' --exclude='migrations/' \
      --exclude='merchant/business-documents/' --exclude='id_cards/' media/ uploads/
# private documents keep the same relative names (the DB stores "merchant/business-documents/…")
rsync -a media/merchant/business-documents/ private_media/merchant/business-documents/
chown -R 10001:10001 uploads private_media && chmod 755 uploads && chmod 750 private_media
find uploads -type f | wc -l ; find private_media -type f | wc -l          # expect 6 in private_media
```

`media_uploads/` (55 photos) goes to `uploads/` like the other public files; nginx keeps denying it until someone
decides whether those photos should be public at all (see step 3).

## 2. Push and the rule 4 checks

Usual checks (health live/ready, 0 pending migrations, 15 min of logs, smoke tests), plus:
- `docker exec qbox-development-web python -c "from django.conf import settings as s; print(s.MEDIA_ROOT, s.QBOX_PRIVATE_MEDIA_ROOT)"`
  → `/app/uploads /app/private_media`
- `docker exec qbox-development-web ls /app/private_media/merchant/business-documents` lists the 3 folders.
- As a merchant with documents: `GET /api/v1/…/business-documents` returns `…/api/v1/files/private/<token>/` links;
  the link downloads (200) with that login, gives 404 with another login and 401 without.
- `GET /warehouses/lookup/` without login → 401; with a merchant login → 200.

## 3. After the push: point nginx at `uploads/`

```sh
TS=$(date -u +%Y%m%d-%H%M); cp -p /etc/nginx/sites-enabled/backend.qbox.sa /etc/nginx/backup/backend.qbox.sa.$TS.bak
sed -i 's#alias /var/www/Qbox-Back-End/media/#alias /var/www/Qbox-Back-End/uploads/#' /etc/nginx/sites-enabled/backend.qbox.sa
grep -n 'alias /var/www/Qbox-Back-End/' /etc/nginx/sites-enabled/backend.qbox.sa   # all 4 media aliases → uploads/
nginx -t && systemctl reload nginx
```

Keep the existing `deny all` blocks (`id_cards`, `merchant/business-documents`, `media_uploads`, `migrations`,
`__pycache__`, `*.py`) — harmless and a second safety net.

Verify: `/media/models.py` → 403 or 404; `/media/merchant/business-documents/…` → 403; one known
`/media/qbox_images/…` and `/media/qrcodes/…` file → 200; `/health/ready/` → 200.

**Rollback (nginx only):** `cp -p /etc/nginx/backup/backend.qbox.sa.$TS.bak /etc/nginx/sites-enabled/backend.qbox.sa && nginx -t && systemctl reload nginx`.

**Rollback (code):** `git revert` the batch; the old code reads `media/` again, which still holds every file (step 1 copied).
Files uploaded after the deploy are in `uploads/` / `private_media/` — copy them back into `media/` before reverting.

## 4. Later (separate step, after a week without problems)

Remove the copied data from the code folder: `media/merchant/business-documents/`, `media/media_uploads/`, the image
and QR folders — keep the `media` app's code. Take a backup first. `backup-daily.sh` already tars `uploads/` and
`private_media/` as soon as they exist (changed 2026-10-07; previous version `backup-daily.sh.20261007.bak`).
