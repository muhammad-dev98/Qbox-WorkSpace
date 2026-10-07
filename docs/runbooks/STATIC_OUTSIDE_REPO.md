# Static files outside the repo (batch head `43c8544f`, prepared 2026-10-07)

Why: `staticfiles/` (221 generated files) was committed to git, and every deploy rewrote it, so `git status` in
`/var/www/Qbox-Back-End` always showed ~200 modified files. From `43c8544f` on, `deploy.sh` writes collectstatic
output to `/var/www/qbox-static` and the repo no longer tracks `staticfiles/`.

The deploy's `git reset --hard` deletes the repo's `staticfiles/` (it stops being tracked). nginx must already read
from `/var/www/qbox-static` by then, otherwise `/static/` (admin, API docs, stream player) 404s for a few minutes.

## Before the owner pushes (agent, ~1 minute, no downtime)

```sh
mkdir -p /var/www/qbox-static && rsync -a /var/www/Qbox-Back-End/staticfiles/ /var/www/qbox-static/
chown -R 1000:1000 /var/www/qbox-static && chmod -R a+rX /var/www/qbox-static
TS=$(date -u +%Y%m%d-%H%M); F=/etc/nginx/sites-enabled/backend.qbox.sa
cp -p $F /etc/nginx/backup/backend.qbox.sa.$TS.bak
sed -i 's#alias /var/www/Qbox-Back-End/staticfiles/#alias /var/www/qbox-static/#' $F
grep -n 'alias /var/www/qbox-static/' $F        # 4 locations: demo.html, whep-player.js, whep-player-logic.js, /static/
nginx -t && systemctl reload nginx
```

Verify: `/static/admin/css/base.css`, `/static/whep-player.js`, `/static/demo.html`, `/api/docs/` → 200.

Rollback: `cp -p /etc/nginx/backup/backend.qbox.sa.$TS.bak $F && nginx -t && systemctl reload nginx`
(only before the push; after it, also run the rollback below).

## After the push

- Deploy log shows "Collecting static files…" and the re-exec (the script continues after `git reset`).
- `/static/…` checks above → 200; `ls -la --time-style=+%F /var/www/qbox-static` shows today's date on `swagger-ui/`.
- `cd /var/www/Qbox-Back-End && git status --short` → empty (only ignored files left).

## Rollback after the push

`git revert` the commit (owner push). The reverted `deploy.sh` writes to the repo's `staticfiles/` again; switch the
nginx aliases back with the backup above.
