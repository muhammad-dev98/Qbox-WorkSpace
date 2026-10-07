# QBOX — FINAL COMPLETION PROMPT (simple pipeline, clean VPS, R2, complete shipping flows)

Save in the workspace root. Start every session with: "Read QBOX_FINAL_COMPLETION_PROMPT.md and PROGRESS.md, then continue with the next unfinished item." This file replaces the process rules of all earlier prompts. Earlier prompts (master, phases 3–13, R2) stay valid only as feature descriptions where this file refers to them.

## 0. How we work from now on (simple)

- One branch: main. Commit locally in logical commits. No gate/* branches, no integration/*, no phase branches.
- One pipeline on GitHub (section 1). The owner pushes main; GitHub does the rest. The agent never pushes main.
- No tests ever run on the VPS. The VPS only builds and runs the app.
- Batching: one push per finished item in section 4 (not per commit). Before handing over a push, the agent runs the test suite locally (throwaway PostgreSQL, as before) and says "ready to push <sha>" with: what's in it, migrations yes/no, backup file name if migrations.
- Reports: short. After each item: what was done, what the owner must do, what's next. No long logs in chat; details go in PROGRESS.md and docs/.
- Secrets: never in chat, commits, logs or docs. Only in root-only files on the VPS. If the agent finds a secret in a working copy, it removes it and tells the owner to rotate it (never to reuse it).
- Decisions the agent may take alone: anything inside this prompt. Ask the owner only for: business data (seller details, prices, policies), money-affecting changes not described here, deleting data, and anything needing a third-party dashboard.

## 1. Simple CI/CD (do first)

Replace all GitHub workflows with exactly two files:

`.github/workflows/deploy.yml` — on push to main (and manual workflow_dispatch):
- job test (GitHub-hosted runner, PostgreSQL + Redis services): install deps, manage.py check, makemigrations --check, ruff, full test suite --parallel (use the runner's cores). Cache pip. Target < 30 min.
- job deploy (needs: test): SSH to the VPS and run deploy.sh. Only runs if test passed.
- concurrency: deploy-main with cancel-in-progress: false so two deploys never overlap.
- On failure, the deploy job does not run and production keeps the previous version.

`.github/workflows/pr.yml` — on pull requests only: the same test job, no deploy.

Remove: the old Tests workflow, gate triggers, the separate Docker build-and-push workflow (unless deploy.sh really uses its image — it does not today), any workflow that deploys without tests.

Owner option: if the owner later wants no tests at all, delete the test job and the needs: line. Default is tests-then-deploy because an untested push already broke production once (confirm-in-qbox 500).

deploy.sh (keep it simple and safe):
- runs from the freshly pulled copy (already done in 43c8544f);
- git fetch && git reset --hard origin/main;
- automatic backup before migrations: if manage.py migrate --plan shows pending migrations, run /root/qbox-ops/backup-daily.sh first and stop the deploy if the backup fails;
- build images at low priority while the old version keeps serving, then migrate, then recreate app containers;
- post-deploy check built in: wait for /health/ready/ = 200 (max 3 min); if it fails, automatically roll back to the previous commit's images and exit non-zero (GitHub shows the failure).
- writes one line per deploy to /var/log/qbox-deploy.log (time, commit, result).

Document the whole flow in docs/runbooks/DEPLOY.md (one page).

## 2. Clean VPS (do second)

Target state of the VPS:
- /var/www/Qbox-Back-End = exactly origin/main; git status shows nothing. Runtime data lives outside the repo: .env.development (root-only), /var/www/qbox-static (static, from 43c8544f), uploads/ and private_media/ only until R2 replaces them (section 3), then removed.
- Delete (archive first to /root/backups/old-code/, copy archives to the development machine, verify checksums, 90-day cleanup cron): Qbox-Back-End-stage0, -stage1, -stage2, -stage-testinfra. Owner approved.
- Remove: /root/qbox-ops leftovers no longer used (old RabbitMQ override, recovery scripts, CI remains), old deploy logs, nginx sites-available backups older than 30 days (keep the latest one per site), unused Docker images (docker image prune for dangling and images not used by the current stack), the MinIO container and volume only in section 3.5.
- Keep: the 3 old panel folders and qbox-inspection-portal until the owner decides; /root/backups; /root/qbox-ops/secrets.
- Log retention 90 days (nginx + app), compressed.
- Write docs/runbooks/VPS_LAYOUT.md: what lives where on the server and why (one page).

## 3. Cloudflare R2 complete (do third)

Feature description: QBOX_R2_AND_SHIPMENT_FLOWS_PROMPT.md section 1. Owner decisions already taken:
- Private bucket only (qbox-private) + backups bucket (qbox-backups). No public bucket and no custom domain until DNS moves from Salla to Cloudflare (separate, later). Store logos and any public image are served through the backend with long cache headers or a presigned URL.
- Credentials: new keys created by the owner after deleting the exposed ones, placed in /root/qbox-ops/secrets/r2.env. The agent never uses the old values (the file ~/qbox-r2-keys-MOVE-TO-VPS-THEN-DELETE.env must be deleted, not moved). If r2.env is missing, do sections 1, 2 and 4 and come back.

Steps:
- django-storages + boto3; STORAGES with default/private → R2 qbox-private; one storage layer replacing core.private_files and shipping.models.private_storage (keep migration-state import paths working).
- Every file type from docs/architecture/STORAGE_INVENTORY.md goes to qbox-private with keys `<area>/<yyyy>/<mm>/<uuid>.<ext>`; downloads only through the existing signed-link view, which re-checks permission, audits, and then redirects to a 5-minute R2 presigned URL. Fix the inventory findings (evidence, payout receipts, home-owner photo off public storage; original filenames out of keys; validate installation_qbox_image_url; delete the unused SSRF-prone base64 fields; save or drop the signup qbox_image_url).
- Upload validation per field (type sniffing, size). Tests with in-memory S3 (no network).
- Copy the existing files (few, mostly test files) to R2 with a manifest and checksums; reversible data migration.
- MinIO removal in the same item once R2 works in production: compose services (development and local), volume (archive first), MINIO_* settings and env vars, minio package, services/minio_service.py, safety rules, docs, uploads/ and private_media/ mounts and folders, nginx /media/ locations. A test fails if minio is imported.
- Backups: nightly encrypted upload to qbox-backups with rclone crypt; password and salt given to the owner once; 30-day lifecycle; restore test from R2 on the development machine; BACKUPS.md updated.

## 4. Complete the shipping business flows (main work)

Feature descriptions: QBOX_R2_AND_SHIPMENT_FLOWS_PROMPT.md section 3 and QBOX_PHASES_3_TO_13_PROMPT.md. One push per item, in this order:

| # | Item | Done when |
|---|---|---|
| 4.1 | Refund bug fix 96b1fceb (owner approved) + static-outside-repo 43c8544f + upload-link batch | deployed, checks green |
| 4.2 | Phase 7 ledger, wallet, tax invoices (ADR 0011) | posting rules doc + test per rule, trial balance job, wallet top-up/holds/statements/credit limit, invoicing app with credit/debit notes, PDFs in R2 |
| 4.3 | Phase 8 outbound completion | versioned rate cards, surcharges, tiers, return fee, promo codes, deposit-overdue, pickup-missed re-book, grouped daily pickup, single-door rules, warehouse hand-over, Qbox-to-Qbox |
| 4.4 | Phase 9 returns R1/R2/R3 | return_type field, ReturnAddress, R3 merchant-paid with SMS/WhatsApp label link, return evidence PDF |
| 4.5 | Phase 10 carrier settlement and payouts | ServiceProvider, CSV/XLSX invoice import, weight variance rules, per-shipment margin, payout batches with maker-checker |
| 4.6 | Notifications (Phase 12 backend) | provider interface (push, SMS, WhatsApp, email), AR/EN templates for every event, preferences, delivery log |
| 4.7 | End-to-end check | the 16 scenarios in the R2 prompt §3.6 all pass with MOCK carrier + simulated Moyasar + device simulator; gaps fixed |
| 4.8 | App-team docs | FLOWS.md (Mermaid per flow), complete OpenAPI, Postman/Bruno collection, MOBILE_CHANGES.md |
| 4.9 | Hardening (Phase 13) | security checklist, PDPL retention jobs, JSON logs, alerts, runbooks, RELEASE_CHECKLIST.md, carrier go-live script |

### Business inputs the agent needs (ask once, then proceed with placeholders)
- Seller details for tax invoices: legal name AR/EN, VAT number, CR number, national address. Until provided, invoices are generated in DRAFT/test mode only and never issued to customers.
- VAT on wallet top-ups: default = prepayment, no VAT at top-up, VAT when credit is spent (current setting); keep it behind a setting until the accountant confirms.
- Prices: rate cards are seeded with clearly marked TEST values; the owner enters real prices in the superadmin settings before go-live.

### Rules that must hold in the finished system (from the business model)
- Receiving is free; sending is paid; customers pay Qbox; Qbox pays carriers and providers; everything reconciled by AWB.
- DELIVERED_TO_QBOX only from the locker door flow (with proof level), never from a carrier status.
- No carrier-specific code outside adapters; SMSA = one adapter + config + mappings + contract tests.
- Every money movement in the balanced ledger; every paid order one invoice; every refund one credit note.
- Single-door Qbox rules (shared door, collection confirmation, pickup warnings) everywhere.

## 5. Still waiting on outside input (never block on these)

SMSA contract/credentials, Moyasar saved-card/void confirmation, accountant sign-off, hardware answers (door sensor, lock feedback, camera, plate format), ELF-484 physical check, frontend main cleanup by the other author, DNS move to Cloudflare, Git history purge of old secrets (owner decision).

## 6. Definition of done (whole project, backend)

- git push origin main by the owner → tests → deploy → health check → automatic rollback on failure. Nothing else needed.
- VPS contains only the live app, its data folders outside the repo, backups and root-only secrets.
- All files in R2 private storage; MinIO gone; encrypted off-site backups with a tested restore.
- All 16 end-to-end scenarios green; docs for the app teams complete; a real carrier can be added with one adapter.
