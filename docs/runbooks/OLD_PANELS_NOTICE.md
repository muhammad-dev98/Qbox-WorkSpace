# Old panels → "new panel coming soon" (prepared 2026-10-07, NOT applied)

Why: the August builds on merchant / super-admin / service-provider.qbox.sa call `https://test.qbox.sa`, which has no
certificate on the VPS and is not an allowed host; their core routes are retired anyway (410). No real use in the logs
(`docs/reports/STABILIZATION_2026-10-07.md` §3). A clear notice is better than a broken app.

## The page

`/var/www/qbox-coming-soon/index.html` (one static file, no scripts, no tracking):

```html
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>Qbox — لوحة جديدة قريبًا / New panel coming soon</title>
  <style>
    :root { color-scheme: light dark; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: system-ui, "Segoe UI", Tahoma, sans-serif;
           background: #f6f7f9; color: #1d2330; }
    @media (prefers-color-scheme: dark) { body { background: #12151b; color: #e8ebf0; } }
    main { max-width: 34rem; padding: 2rem 1.25rem; text-align: center; line-height: 1.6; }
    h1 { font-size: 1.6rem; margin: 0 0 .75rem; }
    p { margin: .25rem 0 1.25rem; }
    hr { border: 0; border-top: 1px solid #8884; margin: 1.5rem 0; }
    [lang="en"] { direction: ltr; }
  </style>
</head>
<body>
  <main>
    <h1>لوحة Qbox الجديدة قريبًا</h1>
    <p>نقوم بتحديث هذه اللوحة. للمساعدة تواصل معنا عبر support@qbox.sa</p>
    <hr>
    <div lang="en">
      <h1>The new Qbox panel is coming soon</h1>
      <p>We are upgrading this panel. For help, contact support@qbox.sa</p>
    </div>
  </main>
</body>
</html>
```

(Replace `support@qbox.sa` with the real support contact before applying.)

## Apply (all three sites, one reload)

```sh
TS=$(date -u +%Y%m%d-%H%M); mkdir -p /etc/nginx/backup /var/www/qbox-coming-soon
# 1. put index.html above into /var/www/qbox-coming-soon/ ; chmod 644
for s in merchant super-admin service-provider; do cp -p /etc/nginx/sites-enabled/$s.qbox.sa /etc/nginx/backup/$s.qbox.sa.$TS.bak; done
sed -i 's#root /var/www/Qbox-Merchant-panel/dist;#root /var/www/qbox-coming-soon;#'      /etc/nginx/sites-enabled/merchant.qbox.sa
sed -i 's#root /var/www/Qbox-Super-Admin/dist;#root /var/www/qbox-coming-soon;#'        /etc/nginx/sites-enabled/super-admin.qbox.sa
sed -i 's#root /var/www/Qbox-Service-Provider/dist;#root /var/www/qbox-coming-soon;#'   /etc/nginx/sites-enabled/service-provider.qbox.sa
nginx -t && systemctl reload nginx
```

Each site's existing `location / { try_files … /index.html; }` then serves the notice for every page. The old
`dist/` folders stay on disk untouched. The `/api/` proxy blocks stay too; nothing loads them any more.

**Verify:** `https://merchant.qbox.sa/`, `https://super-admin.qbox.sa/`, `https://service-provider.qbox.sa/` and any
deep link (e.g. `/dashboard`) show the notice (200); `https://backend.qbox.sa/health/ready/` still 200.

## Rollback (1 minute)

```sh
for s in merchant super-admin service-provider; do cp -p /etc/nginx/backup/$s.qbox.sa.$TS.bak /etc/nginx/sites-enabled/$s.qbox.sa; done
nginx -t && systemctl reload nginx
```
