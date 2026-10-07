# QBOX — PROMPT: CLOUDFLARE R2 (REMOVE MINIO) + COMPLETE THE SHIPMENT FLOWS

Save in the workspace root next to the other prompts. Start each session with: "Read QBOX_AGENT_MASTER_PROMPT.md, QBOX_PHASES_3_TO_13_PROMPT.md, QBOX_R2_AND_SHIPMENT_FLOWS_PROMPT.md and PROGRESS.md, then continue." This file overrides the earlier prompts where they differ. All rules in PROGRESS.md "Rules for backend main" still apply.

## 0. Standing rules (unchanged, repeated because they matter)

- Work on local backend main. The owner runs every push. No push batch without a green GitHub Actions run for that exact commit, run link recorded in PROGRESS.md "Gate runs".
- Never run tests on the VPS. Local throwaway PostgreSQL or GitHub Actions only.
- Fresh production backup before any push that contains migrations or moves data. Rollback steps written before every server change.
- Secrets never appear in chat, commits, logs, docs or reports. Read them only from root-only files on the VPS (/root/qbox-ops/secrets/*.env, chmod 600) or .env.development (chmod 600). Report a secret as "set (N chars)" at most.
- One push batch per finished item below. Report after each batch.

## 1. Replace MinIO with Cloudflare R2 (complete removal)

### 1.1 Credentials (owner provides, agent never asks for them in chat)

The owner places these in /root/qbox-ops/secrets/r2.env (chmod 600) on the VPS:

```
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...          # app token: Object Read & Write, scoped to the app buckets only
R2_SECRET_ACCESS_KEY=...
R2_BACKUP_ACCESS_KEY_ID=...   # separate token: Object Read & Write, scoped to the backup bucket only
R2_BACKUP_SECRET_ACCESS_KEY=...
```

The agent copies the app values into .env.development (never into git). If a value is missing, stop and tell the owner which one. Do not use a Cloudflare account-level API token for anything; the S3 keys are enough. If bucket setup (CORS, lifecycle, custom domain) needs the dashboard, write the exact clicks for the owner instead.

### 1.2 Buckets (owner creates in the Cloudflare dashboard; agent writes the exact list first)

| Bucket | Content | Access |
|---|---|---|
| qbox-private | merchant business documents, ID documents, carrier labels, delivery evidence (photos/clips), invoices / credit notes PDFs, exports | private; downloads only through short-lived presigned URLs issued by the backend after a permission check |
| qbox-public | non-sensitive public assets only (product/Qbox marketing images, sticker previews if public) | public through a custom domain (e.g. media.qbox.sa) with Cloudflare cache; never used for personal data |
| qbox-backups | encrypted database and file backups | private; separate token; lifecycle rule deletes objects after 30 days |

If in doubt whether a file type is personal data, it goes to qbox-private.

### 1.3 Implementation

- Inventory first (write docs/architecture/STORAGE_INVENTORY.md): every place that reads/writes MinIO or local media: settings (MINIO_*), minio client usage, FileField/ImageField with their upload_to and storage, camera/recording code, evidence, labels, private files (commit 073a456c), factory stickers/QR outputs, exports, nginx /media/ locations, compose services/volumes, backup script, docs, requirements.txt. For each: bucket it belongs to, private or public, retention.
- One storage layer using django-storages (S3 backend) and Django's STORAGES setting: storages default → qbox-private, private → qbox-private, public → qbox-public, staticfiles unchanged (nginx serves static).
- Endpoint https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com, region auto, signature v4, default_acl=None, querystring_auth=True for private, file_overwrite=False, sensible object_parameters (content type, Cache-Control for public).
- Presigned GET URLs: default 5 minutes (runtime setting), issued only by views that re-check permission and write an audit event (reuse the 073a456c signed-link pattern; the link now points at R2 or streams through the backend — choose and justify in an ADR).
- Object keys: `<area>/<yyyy>/<mm>/<uuid>.<ext>`; never user-supplied file names in the key; original name kept in the DB.
- Upload validation: allowed MIME types per field, max size, server-side content sniffing, reject executables/SVG with scripts.
- Tests: no network. Use an in-memory/moto S3 or Django's InMemoryStorage in the test settings; add tests for permission checks on every download view, link expiry, audit events, and that no personal-data field uses the public storage (a test that scans field storages).
- ADR docs/adr/00NN-cloudflare-r2-storage.md: buckets, key layout, presign vs proxy, retention, why MinIO is removed.

### 1.4 Data migration (server side, after the code batch is green on GitHub but before the owner pushes it)

- Fresh backup (DB + MinIO volume + media + uploads).
- Copy every object/file to its R2 bucket with rclone (low priority), keeping a manifest (old path → bucket/key, size, sha256).
- Verify: object counts per area match; sha256 of every object matches (download-verify, since R2 multipart ETags are not MD5); DB rows rewritten to new keys via a reversible data migration that is part of the batch.
- Owner pushes. Then rule 4 checks plus: upload a test document, download it through the app (presigned), confirm a stranger gets 403/404, confirm public images load from the custom domain.
- Keep MinIO stopped but not deleted for 14 days as rollback. Rollback = revert the batch + restart MinIO.

### 1.5 Complete removal (separate small batch, ≥14 days after 1.4, owner approves)

Remove: the MinIO compose service and volume (after a final archive copy to qbox-backups), MINIO_* settings and env vars, the MinIO client library from requirements.txt, nginx locations that served MinIO/media files now in R2, MinIO references in docs, runbooks and the backup script, and the safety-check rules about MinIO. Add a test that fails if minio is imported anywhere. Update BACKUPS.md.

### 1.6 Backups to R2 (replaces the Backblaze plan)

- The nightly script uploads DB dump + local-only files to qbox-backups with rclone crypt (encryption password + salt generated once, given to the owner once for the password manager, stored on the VPS root-only).
- Bucket lifecycle 30 days; local VPS copies stay 14 days.
- Restore test from R2 on the development machine (throwaway PostgreSQL), table-by-table row counts vs production; record in BACKUPS.md.
- Note in BACKUPS.md: app files and backups now sit with one provider; a second provider can be added later if the owner wants.

## 2. Merchant document upload without login (close before or with item 1)

- Require the applicant's verified OTP session if the application step has one; otherwise a one-time upload link (single use, 24 h) sent to the applicant's verified phone/email.
- Uploads allowed only while the merchant application is pending; after approval only staff or a logged-in merchant with the right sub-role, audited.
- Rate limit + audit every attempt. List the affected mobile/panel screens in the report.

## 3. Complete the shipment flows on Qbox-Backend

Goal: every flow in the business document works end to end on the backend, with the MOCK carrier, simulated Moyasar and the device simulator, so the mobile apps and panels can be built against a finished API, and a real carrier needs only its adapter.

Order (one push batch each, report after each): 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7.

### 3.1 Phase 7 — Ledger, wallet, tax invoices

As in QBOX_PHASES_3_TO_13_PROMPT.md §6: POSTING_RULES.md with one test per rule, reversal entries, nightly trial-balance job with alert, wallet top-up / holds / statements / credit limit, invoicing app (gap-free numbering, hash chain, QR, AR/EN PDF stored in qbox-private, credit notes for refunds, debit notes for adjustments), LocalInvoiceProvider now, ZatcaFatooraProvider stub. VAT mode and revenue recognition stay behind settings until the accountant signs off.

### 3.2 Phase 8 — Outbound completion

Versioned immutable rate cards, min charge, surcharges (fuel, remote area, oversize, declared-value protection), merchant tiers, return fee, promo codes, full input snapshot on the quote; DEPOSIT_OVERDUE (reminder, auto-cancel + refund minus fee), PICKUP_MISSED (auto re-book N times, then ops task); one grouped pickup per Qbox per day; single-door rules; warehouse hand-over kept; Qbox-to-Qbox recipient side.

### 3.3 Phase 9 — Returns

return_type field (data migration from metadata), ReturnAddress, R1/R2/R3 complete, R3 merchant-paid from wallet with SMS/WhatsApp label link, return evidence PDF in qbox-private.

### 3.4 Phase 10 — Provider settlement and payouts

ServiceProvider, CSV + XLSX invoice import, WEIGHT_VARIANCE + variance rules, per-shipment financials and gross margin, PayoutBatch with maker-checker, PayoutRail (manual), prepaid carrier balance, payables aging and cash-position report.

### 3.5 Phase 12 backend — Notifications

NotificationProvider interface (FCM push, SMS, WhatsApp, email; mock), AR/EN templates for every shipment, payment, door and single-door event, user preferences, delivery log, retries.

### 3.6 Flow completeness check (no new features; fill gaps only)

Build a shipments/tests/e2e/ suite with one test per scenario, all green, using MOCK carrier + simulated Moyasar + device simulator:

1. Inbound happy path → DELIVERED_TO_QBOX (door events) → COLLECTED; carrier "Delivered" alone never delivers.
2. Inbound unknown tracking → ask owner → approve → delivered.
3. Wrong tracking 5× → portal lockout; Qbox full / won't fit.
4. Outbound homeowner: quote → order → card payment → AWB + label (in qbox-private) → deposit → grouped pickup → pickup code → picked up → delivered; ledger balanced; invoice issued.
5. Outbound merchant from Qbox with wallet payment; and from warehouse with hand-over.
6. Split wallet + card, card fails → credit hold released, ledger reversal.
7. Booking timeout then success → exactly one AWB.
8. Booking permanent failure → BOOKING_FAILED → full refund → credit note.
9. Cancel before pickup → carrier cancel → refund minus fee; after pickup → NOT_CANCELLABLE.
10. Weight adjustment from carrier invoice → saved card / wallet / payment link → debit note.
11. Carrier invoice reconciliation with variances → payout batch → maker-checker → paid.
12. Returns R1, R2, R3.
13. Deposit overdue → reminder → auto-cancel; pickup missed → re-book.
14. Qbox-to-Qbox send to an opted-in recipient.
15. DEGRADED delivery → owner confirms / reports missing → incident.
16. Single door with inbound and outbound parcels inside → driver guidance, owner warning, block-pickups policy.

Every gap found becomes a fix in this batch, with its test.

### 3.7 API and flow documentation for the app teams

- docs/shipments/FLOWS.md: per flow, a Mermaid sequence diagram (actor → endpoint → state change), the states on the wire, and the available_actions the app should show at each step.
- OpenAPI complete for every endpoint used in 3.6, with request/response examples and error codes; a Postman/Bruno collection generated from it that runs the happy paths against a dev environment.
- docs/shipments/MOBILE_CHANGES.md: every change the homeowner and merchant apps must make since the version they ship today (new states, new endpoints, removed routes), ordered by priority.

### Definition of done for section 3

All 16 scenarios green on GitHub Actions; trial balance balances after every scenario; every paid order has exactly one invoice and every refund one credit note; no carrier-specific code outside adapters; FLOWS.md, OpenAPI and MOBILE_CHANGES.md complete; deployed with rule 4 checks.
