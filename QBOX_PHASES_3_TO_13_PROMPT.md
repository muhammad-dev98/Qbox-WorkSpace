QBOX — CONTINUATION PROMPT: PHASES 3 TO 13

Save next to QBOX_AGENT_MASTER_PROMPT.md in the workspace root. Start each session with: "Read QBOX_AGENT_MASTER_PROMPT.md (including §15 owner decisions), QBOX_PHASES_3_TO_13_PROMPT.md and PROGRESS.md, then continue with the next unfinished phase."

This file overrides the master prompt wherever they differ. Everything in the master prompt that is not changed here still applies (standards §1, rules §0, "must not" list §14).

0. Answers to your Phase 1–2 report (do these first)
0.1 Branch correction (before anything else)

The agreed rule was: Phase 1+ on a new branch, not on main, until Release R is deployed. Phases 1–2 were committed to local backend main, and a push to main deploys to the VPS. Fix this without losing work:

git branch feat/master-phases-1-2 at the current local main HEAD.
Verify the branch contains every Phase 1–2 commit (git log origin/main..feat/master-phases-1-2).
Only then reset local main to origin/main (git reset --hard origin/main on main only). Show me the two logs before running the reset.
From now on: one branch per phase off feat/master-phases-1-2 (or its successor), PRs into an integration branch, never commit to main. Add a local pre-push hook that refuses pushes to main from this workspace.
Rerun the full suite on a fresh database on the branch head and record the result in PROGRESS.md. Every phase gate from now on = full suite on a fresh DB, not a subset.
0.2 Approvals
Hotfixes (a) wallet credit release, (b) shared VAT rounding, (c) cancelled-order payment refund: approved for Release R, each as its own PR with its failing-without-fix test. Include a ledger reversal for (a) and (c), and an audit event for every automatic refund.
Compartment sharing: keep shared mode (several parcels behind one door). See §1.
drf-yasg staying: accepted. Add an ADR and a backlog item to migrate later; no new code may use drf-yasg.
Temporary worktrees: list them in PROGRESS.md; I will delete them.
0.3 Owner actions (I handle these; do not attempt them)

Secret rotation (SECRET_KEY, Moyasar, WhatsApp, SPL, EMQX), git-history purge, VPS DEBUG=False, moving the private key files off the VPS repo folder. After I confirm rotation, you will: add gitleaks (or similar) to CI and a pre-commit hook, and add a startup check that refuses to boot in production with DEBUG=True, a default SECRET_KEY, or missing required secrets.

1. Hardware reality (overrides master prompt §3, §4, §6 compartment parts)

Qbox currently has one product: a single-door smart locker (photos confirmed), with:

one large parcel door with an electronic lock;
an external camera window ("Show QR here") at the top;
metal QR plates (side panel and door) and a metal number plate (e.g. AA 0003);
a top "Documents Here" drawer with a mechanical combination lock — not connected to the platform.

Rules:

Keep the Compartment model that Phase 2 built (every Qbox has exactly one compartment today). Do not delete it; it costs nothing and keeps a future multi-door product possible. But remove compartment complexity from the product: no compartment allocation UI, no compartment picker, no "smallest-fit" logic exposed in any panel or API response for single-compartment devices. Allocation always returns the single door. Hide compartment tables in the factory panel unless the device model has more than one.
DeviceModel gets capability flags: door_count, has_door_sensor, has_lock_feedback, has_external_camera, has_evidence_camera, has_documents_drawer_electronic (false), supports_offline_tokens. All flows read capabilities; nothing hard-codes hardware assumptions.
Shared door, multiple parcels — required rules:
Occupancy: track parcels currently IN_QBOX per Qbox. Owner-configurable soft capacity (default: no limit) and a "Qbox is full" toggle the owner or driver ("Won't fit / Qbox full") can set; when full, the portal tells the driver to use the carrier fallback and the owner is notified.
Owner collection: when the owner opens the door with a collect token and the door closes, show the owner the list of parcels that were inside and let them confirm which were collected (default: all). Unconfirmed after 24 h → mark all COLLECTED, audited.
Mixed inbound + outbound in one door (security): a pickup driver opening the door can see inbound parcels, and a delivery driver can see an outbound parcel. Mitigations, all required:
Portal shows the driver exactly which parcel to take or leave (AWB/tracking, and the photo from deposit if available).
Every driver opening is recorded (evidence) and notified to the owner in real time.
When an outbound pickup is booked while inbound parcels are inside, warn the owner in the app ("Collect your parcels before the pickup window") and remind them 1 h before the window.
Owner policy setting: "Block pickups while my parcels are inside" (default off).
Number plate vs code: the physical plate shows AA 0003 style numbers while the platform qbox_code is ABC-234. Drivers will type what is printed. Add plate_number (unique, permanent, normalized without spaces/case) to the device. The portal and every lookup accept either qbox_code or plate_number. The factory sticker generator and plate order sheet print both. Write ADR 0005.
Existing metal QR plates: they may encode the old device token, not the portal URL. Add a factory-panel tool "Check a printed QR" where staff paste or upload a scan; it reports whether it is the signed portal URL, a legacy device token, or unknown, and for legacy plates generates the replacement sticker. Add a fleet report: devices whose installed plate is not yet verified.
2. Phase 3 — Device contract v2, door proof, access tokens

Prerequisite: hardware team approval of contracts/api/locker-device-v2.md. While waiting, do Phases 4 and 6 first; build Phase 3 only to the parts that do not need firmware changes.

Door proof (the most important question). DELIVERED_TO_QBOX must come from physical evidence. Implement a proof_level on every door session and every delivered shipment:

FULL: unlock executed + door-open sensor + door-closed sensor (+ evidence clip if camera exists).
LOCK_FEEDBACK: lock reports locked again after the session, no door sensor.
DEGRADED: only unlock acknowledgement + driver "I closed the door" in the portal + evidence clip. Rules: the shipment becomes DELIVERED_TO_QBOX in all three, but proof_level is stored, shown in the owner app and the superadmin evidence view, and used in dispute reports. DEGRADED triggers an owner prompt "Confirm parcel is in your Qbox". Add a fleet report of devices without a door sensor. The v2 contract asks hardware for a reed switch on the door as a requirement for FULL.

Access tokens v2:

Ed25519 signed tokens with kid, rotation command with grace period, GET /devices/keys/.
Offline verification + local used-nonce list + POST /devices/offline-sync/; a nonce used twice → SecurityIncident (new model: type, device, severity, status OPEN/ACK/RESOLVED, linked events) visible in superadmin.
Keep today's opaque codes working behind a token_format per device (OPAQUE_V1, SIGNED_V2) until all devices are upgraded.

Device API completion: batched door events (POST /devices/events/ accepts an array, idempotent per device_event_id, ordered by sequence number), FORCED_OPEN / TAMPER / DOOR_LEFT_OPEN incidents, HTTPS command poll + ack as a fallback to MQTT, PING and SYNC_KEYS commands, evidence upload via pre-signed URL with retention_until from SystemSetting. Introduce the DeviceTransport interface (MQTT, HTTPS) so services never call MQTT directly.

Acceptance: simulator scenarios for each proof level; offline delivery then sync; nonce reuse creates an incident; door left open creates an incident and notification; full suite green.

3. Phase 4 — Carrier framework (SMSA-ready, any carrier)

Goal: when SMSA (or Aramex, SPL, Naqel, J&T, DHL, iMile) credentials arrive, integration = one adapter class + config rows + mapping rows + contract tests. No change to shipments, payments, ledger, portal or panels.

Adapter contract — add: validate_address, cancel_pickup, verify_webhook, parse_webhook, import_invoice. Rich CarrierCapabilities (rates_api, cancel_before_pickup, cancel_after_pickup, pickup_api, pickup_windows, label_formats PDF/ZPL, multi_piece, cod, returns, webhooks, address_validation, max_weight_g, max_side_mm, serviceable_cities, idempotency_supported, invoice_api). Business services check capabilities and fall back (rate card / manual ops task / polling).
Config-driven registry: adapter class path stored on Carrier; no hard-coded if code ==. A carrier can be enabled/disabled per environment from superadmin.
Mapping models: CarrierStatusMapping (carrier, raw code → normalized) migrating the AfterShip TAG_MAP and SMSA JSON map into rows; CarrierCityMapping + shared CityAlias table (Arabic + English names, common misspellings). Unmapped status or city → stored, flagged, shown in an "Unmapped inbox" in superadmin, alert.
Reliability: error classes Retryable / Permanent / Auth / RateLimited; backoff with jitter; per-carrier-account circuit breaker (state visible in superadmin); CarrierApiCall log (operation, redacted request/response, status, latency, correlation id, shipment, retention from SystemSetting).
Webhooks: generic POST /api/v1/carriers/webhooks/{carrier_code}/ → verify → store raw → dedupe → outbox → normalize → apply. Keep the existing tracking webhook route as an alias.
Mock carrier scenarios selectable per shipment (non-production only): success, timeout_then_success, invalid_city, booking_fails, auth_error, pickup_missed, weight_adjustment, lost_in_transit, returned_to_sender, cancel_rejected_after_pickup.
Labels: signed short-lived download URLs; PDF and ZPL; "driver brings label" flag on the shipment (when the carrier capability allows).
Address: AddressResolver interface (manual/mock now, SPL National Address implementation behind config), storing raw input + resolved structure.
SMSA readiness pack: update docs/shipments/SMSA_GO_LIVE.md into a checklist of every question to confirm with SMSA (auth, reference field, pickup API, cancellation rules, label formats, webhook signature, invoice export, sandbox), and a contract-test file with empty fixtures per operation. Same template as docs/carriers/CARRIER_ONBOARDING_TEMPLATE.md for any other carrier.

Acceptance: every mock scenario has an end-to-end test; a second dummy carrier (MOCK2) is added using only the onboarding template to prove no core code changes are needed — commit the diff summary as evidence.

4. Phase 5 — Inbound completion + Driver Portal app

Backend:

DriverSession as a stateful model (started, language, attempts, failures, lockout, actions, current step).
OwnerApprovalRequest (ask-owner flow): push to owner with tracking number and camera snapshot (if camera supports it); approve/reject from app; expiry default 3 min (SystemSetting); approve → register shipment + issue delivery token.
wont-fit / qbox-full endpoint: records the event, notifies the owner, tells the driver to use carrier fallback.
GET /driver/session/status/ (polling; SSE optional) for door progress.
Additive inbound states: ATTEMPT_FAILED, AT_CARRIER_POINT, NOT_ELIGIBLE (COD / signature, set at registration from user flags or carrier data). Keep wire names per §15; add display labels.
Late-arrival rule: driver arrives before OUT_FOR_DELIVERY → force live tracking refresh → issue token if registered and not delivered (owner setting "strict" disables this).
Optional second factor: last 4 digits of recipient phone (owner setting).
Accept plate_number everywhere a qbox_code is accepted.

Frontend — new app apps/driver-portal:

Public, isolated (no panel code, no auth package), static export, served at /d/:code. Replaces the server-rendered page once at parity (keep the old page as fallback for one release).
Languages AR, EN, UR, HI, BN with RTL; language auto-detected from the phone, switcher visible.
Screens: landing (code, plate number, official domain, sticker-check warning) → Deliver / Pick up → enter tracking/AWB (manual + camera barcode scan with fallback) → full-screen QR (wake-lock, brightness hint, countdown) → live door status → done / deliver another. Error screens: not registered (ask owner), Qbox full / won't fit, offline, locked out, expired, not eligible (COD).
Performance budget: < 150 KB JS gzipped for first load, works on 3G, usable with one hand, large touch targets.
Playwright tests for deliver, pickup, ask-owner, lockout, every language renders.

Acceptance: master prompt E2E scenarios 1–3 pass with the device simulator; portal Lighthouse mobile performance ≥ 90.

5. Phase 6 — Payments hardening
One PaymentGateway interface (delete unused financial/providers.py after confirming no imports): create, fetch, verify, refund (partial), void, tokenize card, charge saved card, parse/verify webhook. Moyasar implementation + simulated + fake.
Split payment (credit + card) uses a hold on credit, converted on payment success and released on failure/expiry/cancel (generalise hotfix (a)).
Saved cards: explicit consent record, encrypted token, list/delete endpoints, default card, used only for adjustments and merchant auto-top-up.
Refund destination choice (original method or wallet) where policy allows; refunds above a SystemSetting threshold require FINANCE_APPROVER.
ChargeAdjustment (weight adjustment, surcharge, damage fee) with carrier evidence, customer notification, charge to wallet → saved card → payment link fallback; unpaid adjustments flag the account and block new outbound shipments until paid (owner-configurable).
Chargebacks/disputes from Moyasar recorded as PaymentDispute with ledger postings.
Legacy /payments/… and legacy wallet/ledger/refund/invoice/payout routes → 410 with errors.code = LEGACY_ENDPOINT_RETIRED, after confirming with access logs that no current client calls them (report findings first).

Acceptance: scenarios 6, 8, 9, 10; Moyasar webhook replay/forgery tests still pass.

6. Phase 7 — Ledger, wallet, tax invoices
docs/finance/POSTING_RULES.md: every money event → its journal entry, with one test per rule.
Generic reversal entries (never edit/delete); nightly trial-balance job with alert; ledger explorer API (account, period, entries, drill-down to source object).
Wallet: top-up via Moyasar, holds, statements (PDF/CSV), optional auto-top-up with saved card, credit limit for approved enterprise/merchant accounts (FINANCE_APPROVER sets it). Run the legacy wallet migration command in staging, reconcile totals, report; production run is an owner decision.
invoicing app: EInvoicingProvider interface; LocalInvoiceProvider now; ZatcaFatooraProvider stub with config slots. Simplified invoice (consumer) / standard invoice (VAT-registered merchant, buyer VAT number captured on the account), credit notes for refunds, debit notes for adjustments. Gap-free sequential numbering per series using a locked counter row, previous-invoice hash chain, QR field, AR/EN PDF. Issued documents are immutable.
Revenue recognition and VAT mode remain behind settings until the accountant signs off; document the current assumption in an ADR.

Acceptance: trial balance balances after every E2E scenario; every paid order has exactly one invoice; every refund exactly one credit note.

7. Phase 8 — Outbound completion
Pricing: versioned rate cards (immutable once active; new version to change), min charge, surcharges (fuel %, remote area by city/district, oversize, declared-value protection), merchant volume tiers, return fee, promo codes (usage limits, expiry, per account), full input snapshot on the quote.
Additive outbound states: DEPOSIT_OVERDUE (reminder at X days, auto-cancel + refund minus fee at Y days, from SystemSetting), PICKUP_MISSED (auto re-book up to N times, then ops task + owner notice).
Pickups: one carrier pickup per Qbox per day groups all ready parcels (homeowner and merchant); pickup window selection when the carrier supports it.
Single-door rules from §1.3 applied to pickups.
Merchant warehouse hand-over path kept.
Qbox-to-Qbox: recipient side gets delivery token, notification and collection exactly like normal receiving; sender stays masked.

Acceptance: scenarios 4, 5, 7, 14 including grouped pickup and missed-pickup rebooking.

8. Phase 9 — Returns
Explicit return_type field (R1/R2/R3) replacing metadata.return_type (data migration).
ReturnAddress (merchant-owned + platform-curated popular store addresses, admin-managed).
R3 merchant-paid returns: merchant creates from panel, pays from wallet, end customer receives label link by SMS/WhatsApp, drops at carrier, it arrives into the merchant's Qbox via normal receiving (or merchant warehouse).
Evidence report for returns (deposit clip + pickup clip) downloadable as PDF for the customer's refund claim with the store.

Acceptance: scenario 12 for R1, R2, R3.

9. Phase 10 — Provider settlement and payouts
ServiceProvider (carrier, tracking, notifications, installer, other) with encrypted bank details, VAT number, payment terms, currency.
Provider invoice import CSV + XLSX (and adapter import_invoice when available); line statuses add WEIGHT_VARIANCE; variance rules from SystemSetting (absorb under threshold, else ChargeAdjustment or carrier dispute).
Per-shipment financials: quoted cost, actual cost, surcharges, payment fee, revenue lines, gross margin, settlement status; margin report by carrier, service, account type, month.
PayoutBatch with maker-checker (creator cannot approve; FINANCE prepares, FINANCE_APPROVER approves and marks paid with bank reference). PayoutRail interface (manual now). Prepaid carrier balance option with low-balance alert.
Payables aging and cash-position report (customer money collected vs owed to providers).

Acceptance: scenario 11 end to end; maker-checker enforced by tests.

10. Phase 11 — Merchant panel (complete)

Merchants use the same single-door Qbox plus optional warehouse. Build on fix/merchant-canonical-shipments once merged.

Adopt merchant sub-roles in backend endpoints and panel guards (owner, admin, shipping, receiving, finance, viewer).
Overview, Qbox status (online, door state, parcels inside, full toggle, door history with evidence).
Receiving: single + CSV bulk import (validation report), approve ask-owner requests, filters, timelines, proof level.
Sending: address book, National Address lookup, parcel presets, quotes by carrier/service, checkout (wallet/card/split), PDF/ZPL labels, origin Qbox or warehouse, grouped daily pickup view, bulk CSV create.
Returns R1/R2/R3, return addresses.
Wallet & billing: top-up, saved cards, statements, invoices/credit/debit notes, adjustments with evidence.
Team, Developers (scoped API keys, outgoing webhooks with signing secret and delivery log), Reports.
Shared halala money formatter in packages/utils; AR/EN everywhere.
Archive service-provider-panel (its backend is retired).

Acceptance: merchant Playwright E2E against a seeded backend (not only mocked routes): receive, send + pay, label, return, wallet top-up.

11. Phase 12 — Superadmin panel + notifications
Superadmin: dashboard (stuck states, booking/payment success, webhook lag, online fleet, revenue, margin), shipments with three status tracks and full timeline, disputes & evidence (proof level, PDF report), fleet (devices, door state, commands with reason, incidents, plate verification report), carriers (accounts with masked credentials + test connection, services, mappings, unmapped inbox, rate cards, circuit breakers, API call log), pricing & promos, finance (payments, refunds approval, adjustments, wallets, ledger explorer, trial balance, provider invoices, reconciliation, payout batches, tax documents), accounts & roles, SystemSetting editor, notification templates, simulators (non-production), audit log.
Notifications: NotificationProvider interface (push FCM, SMS, WhatsApp, email; mock), AR/EN templates for every event in master prompt §10 plus single-door events (Qbox full, collect before pickup, proof DEGRADED confirm), user preferences, delivery log, retries.

Acceptance: superadmin E2E for refund approval, payout maker-checker, rate-card publish, device command with reason.

12. Phase 13 — Hardening and go-live readiness
Security review (OWASP ASVS L2 checklist), dependency audit, secret scanning in CI, production boot checks, rate limits verified, PII redaction verified in logs.
PDPL: retention jobs for video/evidence, carrier API logs, addresses of closed accounts; data export and deletion endpoints; access to evidence audited.
JSON structured logs; dashboards and alerts (stuck states, trial balance, webhook failures, device offline rate, circuit breakers).
Backups and a tested restore runbook; zero-downtime migration checklist; feature flags for each new flow.
Load tests: carrier/payment webhooks burst, driver portal concurrent sessions, device event ingestion.
docs/RELEASE_CHECKLIST.md, docs/runbooks/ (carrier outage, payment outage, device offline, stuck booking, refund failure, security incident).
Carrier go-live script: steps to switch a carrier account from SANDBOX to PRODUCTION, smoke tests, rollback.
13. Rules for every phase (reminder)
Branch per phase, PR, never main. Full suite on a fresh DB at every gate; record in PROGRESS.md.
Ask before: data migrations on production-shaped data, removing routes, anything touching money in Release R.
Stop and report when hardware, accountant, SMSA or other vendor input is needed; continue with the next independent phase.
Keep wire status names (§15); new states additive; mobile apps must keep working.
