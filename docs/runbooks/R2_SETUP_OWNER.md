# Cloudflare R2 — setup steps for the owner (2026-10-07)

The agent never sees or asks for these values in chat. Everything below is done in the Cloudflare dashboard
(dash.cloudflare.com) by the owner; the last step puts the keys on the VPS.

## 0. Decision needed first: the public bucket's domain

`qbox.sa` DNS is hosted at **Salla** (`ns1/ns2.salla.cloud`), not Cloudflare. An R2 **custom domain**
(`media.qbox.sa`) only works for a domain whose DNS is a Cloudflare zone. Options:

| Option | What it takes | Recommendation |
|---|---|---|
| A. Move `qbox.sa` DNS to Cloudflare (free plan) | Add the site in Cloudflare, copy every DNS record from Salla (Cloudflare imports most), switch the nameservers at the registrar. Email (MX), Salla store records and every `*.qbox.sa` subdomain must be copied exactly. | Best long term (cache, WAF), but it touches every subdomain and email — plan it as its own change |
| B. Serve public files through our nginx | `media.qbox.sa` → VPS nginx → R2 (no DNS move; one DNS A record at Salla) | Works now; VPS carries the traffic (small today) |
| C. No public bucket yet | All files private, presigned links only; `qbox-public` created but unused | Simplest; fine while there are no marketing images |

The agent's recommendation: **C now, A later** as a planned DNS move. Tell the agent which one.

## 1. Create the buckets

R2 Object Storage → **Create bucket**, three times:

| Name | Location | Default storage class |
|---|---|---|
| `qbox-private` | Automatic (or "Europe" if you want EU data residency — keep all three the same) | Standard |
| `qbox-public` | same | Standard |
| `qbox-backups` | same | Standard |

Leave **Public access** off on all three (R2 → bucket → Settings → Public access: "R2.dev subdomain: Not allowed").
Do not enable the r2.dev subdomain on any bucket — it is rate-limited and not meant for production.

## 2. Lifecycle rule on `qbox-backups`

`qbox-backups` → Settings → **Object lifecycle rules** → Add rule:
- Name: `expire-30-days`; applies to: all objects (no prefix);
- Action: **Delete uploaded objects** after **30 days**;
- also tick **Abort incomplete multipart uploads** after **1 day**.

On `qbox-private` and `qbox-public`: only add the "abort incomplete multipart uploads after 1 day" rule (no expiry).

## 3. CORS on `qbox-private` (only needed if browsers download straight from R2)

`qbox-private` → Settings → **CORS policy** → Edit, paste:

```json
[
  {
    "AllowedOrigins": ["https://merchant.qbox.sa", "https://super-admin.qbox.sa", "https://backend.qbox.sa"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 300
  }
]
```

(No PUT: uploads go through the backend, which validates every file.)

## 4. API tokens (two, S3 keys only)

R2 Object Storage → **Manage R2 API Tokens** → **Create API token**:

1. **App token** — name `qbox-app`; permission **Object Read & Write**; **Specify bucket(s)**: `qbox-private`,
   `qbox-public`; TTL: forever (rotate yearly); no IP filter for now.
2. **Backup token** — name `qbox-backups`; permission **Object Read & Write**; **Specify bucket(s)**: `qbox-backups` only.

Each shows an **Access Key ID** and **Secret Access Key** once. The **Account ID** is on the R2 overview page
(right side). Do **not** create an account-level "API token" — the S3 keys are enough.

## 5. Put the keys on the VPS (root only)

```sh
ssh root@69.62.125.223
umask 077; nano /root/qbox-ops/secrets/r2.env
```

```
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BACKUP_ACCESS_KEY_ID=...
R2_BACKUP_SECRET_ACCESS_KEY=...
```

```sh
chmod 600 /root/qbox-ops/secrets/r2.env
```

Then tell the agent "r2.env is in place". The agent reports each value only as "set (N chars)".
