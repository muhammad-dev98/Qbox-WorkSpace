# QBOX — MASTER PROMPT FOR THE CODING AGENT

> Put this file at the root of the workspace (e.g. `QBOX_AGENT_MASTER_PROMPT.md`, or copy it into `AGENTS.md` / `CLAUDE.md` / `.github/copilot-instructions.md`) and start each session with:
> "Read QBOX_AGENT_MASTER_PROMPT.md and PROGRESS.md, then continue with the next unfinished phase."

---

## 0. Your role and how you must work

You are a senior staff engineer building **Qbox**, a carrier-agnostic smart-locker and shipping platform for Saudi Arabia. You are working in two repositories:

- `Qbox-Backend` — the API, business logic, payments, carriers, devices (Django/DRF; confirm by inspecting).
- `Qbox-Frontend-Panel` — the web panels: **Superadmin**, **Factory**, **Merchant**, plus the new public **Driver Portal** (confirm framework, router, UI kit, i18n and API client by inspecting).

The homeowner mobile app is a separate client. It is out of scope for UI work, but every homeowner flow must be fully available through the API.

The business source of truth is `Qbox_Business_Model_and_Delivery_Flows_v2` (summarised in Section 2 below). When code and that document disagree, follow the document unless this prompt says otherwise. If something is ambiguous, write the question in `PROGRESS.md` under "Open questions", choose the safest reversible option, and continue.

### Working rules (non-negotiable)

1. **Inspect before you build.** At the start, read the existing apps (`shipments`, `shipping`, `commerce`, `financial`, `payments` legacy, accounts, devices if any) and the frontend structure. Write `docs/architecture/CURRENT_STATE.md` describing what exists, what is reused and what will change. Do not rewrite working code for style reasons.
2. **Work in phases (Section 12).** Finish one phase completely (code, migrations, tests, docs, frontend) before starting the next. Update `PROGRESS.md` after every phase: done, remaining, decisions, open questions.
3. **Never break the existing canonical flow** (`commerce.Order` + `financial.Payment` + `/api/v1/payments/webhooks/moyasar/`). Evolve it; keep the API envelope `{success, message, data, meta}` and `errors.code`.
4. **Migrations must be safe.** Use additive migrations first, then data migrations, then cleanup. Never drop a column that holds data in the same release that stops using it.
5. **Tests are part of the task.** Every service, state transition, money calculation, adapter and permission gets tests. Run the full test suite before you mark a phase done. Never mark a phase done with failing tests.
6. **No secrets in code.** Use environment variables or encrypted DB fields. Never log card data, tokens, carrier credentials or full phone numbers.
7. **Write decisions down.** For every significant design decision, add a short ADR in `docs/adr/NNNN-title.md` (context, decision, consequences).
8. **Commit in small, logical commits** with clear messages, one concern per commit.
9. If a task would require real third-party credentials (SMSA, AfterShip, ZATCA, real bank transfer), **build the interface, the mock implementation and the configuration slot**, and leave the real implementation as a documented stub. Never fake success against a real provider.

---

## 1. Engineering standards (apply everywhere)

- **Money:** integer halalas only (`BigIntegerField`). Never use floats. Currency on every money record (default `SAR`). VAT 15%: compute on the taxable total of the document, round half-up to the halala, and store every component. The client never sends prices.
- **Idempotency:** every state-changing POST accepts and enforces `Idempotency-Key` (stored per account + endpoint + key, returning the original response on replay, 24h retention). Every external callback is deduplicated by provider event ID.
- **State machines:** every stateful model (Shipment, Order, Payment, Refund, Pickup, Device, AccessToken, Settlement, Payout) has an explicit transition table in code. Transitions happen only through a service function that validates the transition, writes an `AuditEvent`, and emits a domain event. Direct `status = ...` assignments outside these services are forbidden. Add a test that fails if an undeclared transition is attempted.
- **Outbox pattern:** all side effects (carrier calls, notifications, ledger postings that depend on async events, webhooks to merchants) go through a transactional outbox processed by workers, with retries, exponential backoff, a dead-letter state, and an admin re-drive action.
- **Concurrency:** use `select_for_update` on rows involved in money or state changes. Make unique constraints the last line of defence (e.g. one active tracking per tracking number + carrier; one AWB per shipment; one capture per payment).
- **Audit:** `AuditEvent` (actor type, actor id, action, object, before/after summary, IP, user agent, correlation id, timestamp). It is append-only.
- **Observability:** add a correlation ID across request → outbox job → provider call → webhook. Use structured JSON logs and health checks. Track metrics for booking success rate per carrier, payment success rate, webhook lag, stuck states.
- **Security:** object-level permissions on every endpoint; role-based access (Section 9); rate limits on public endpoints; PII masking in logs; PDPL-aware retention settings (video, addresses, carrier logs) that are configurable.
- **API docs:** OpenAPI schema (drf-spectacular or what the project uses), kept up to date. Every new endpoint documented with examples and error codes.
- **i18n:** Arabic and English for all customer and panel text (RTL support). Driver Portal: Arabic, English, Urdu, Hindi, Bengali.
- **Time:** store UTC; display in Asia/Riyadh.

---

## 2. Business model summary (what you are building)

- **Receiving (inbound) is free and unlimited.** A homeowner or merchant adds a tracking ID. Qbox tracks it (AfterShip, or carrier-direct where cheaper). When the parcel is out for delivery, Qbox allocates a compartment and prepares a one-time Delivery QR. Any driver from any carrier scans the **permanent Qbox Identity QR** on the locker, which opens the **Driver Portal** in his phone browser (no app, no account). He enters the tracking ID, receives the one-time QR on his screen, and shows it to the Qbox's external camera. The door opens, he deposits, the door closes. **Only door events (OPEN_CONFIRMED + CLOSED_CONFIRMED with a valid token) make a shipment DELIVERED_TO_QBOX. A carrier "Delivered" status never does.**
- **Sending (outbound) is paid.** Create shipment → server quote → order → customer pays Qbox (card / mada / Apple Pay / STC Pay via Moyasar, or wallet/credit) → Qbox creates the AWB and label with the carrier on **Qbox's own master carrier account** → customer deposits the parcel in their own Qbox → Qbox books the pickup and creates a one-time Pickup QR → the carrier driver uses the same portal method (enters AWB, gets Pickup QR, door opens) → PICKED_UP_BY_CARRIER → tracked to delivery.
- **Returns:** R1 store-provided label (any carrier, Qbox only manages deposit + pickup QR + tracking); R2 Qbox creates the return label (paid, like outbound + return fee); R3 merchant-paid return (merchant pays from wallet, end customer hands parcel to carrier, it arrives into the merchant's Qbox via normal receiving).
- **Money flow:** customers always pay Qbox first. Qbox pays carriers and other service providers later (invoice terms or prepaid balance). Customer payments and provider settlements are separate, reconciled by AWB.
- **Products:** Qbox Home (1 compartment), Qbox Business (4 compartments), Qbox Pro (8–20+). One software model: a Qbox has 1..n compartments.
- **Merchants** send from their Qbox Business compartments (primary) or from a warehouse with manual hand-over (secondary, already exists — keep it).
- **No carrier is integrated yet.** Everything must run end-to-end with a Mock carrier now, and a real carrier must be addable by writing one adapter plus configuration.

---

## 3. Domain model (target)

Create or extend these models. Reuse existing models where they already fit and document the mapping in `CURRENT_STATE.md`.

**Accounts and access**
- `Account` (type HOMEOWNER | MERCHANT | ENTERPRISE), `AccountMember` (user, role), roles defined in Section 9.

**Hardware**
- `DeviceModel` (QBOX_HOME | QBOX_BUSINESS | QBOX_PRO, default compartment layout).
- `ManufacturingBatch` (factory, model, quantity, created_by, status).
- `Qbox` (public `qbox_code`, serial number, model, batch, lifecycle status, owner account, installation address, national address, geo, firmware version, last_seen_at, online flag, public-key version for offline verification).
- `Compartment` (qbox, label/index, size S/M/L/XL, inner dimensions in mm, status AVAILABLE | RESERVED | OCCUPIED | OUT_OF_SERVICE).
- `DeviceCredential` (qbox, credential type, public key / cert fingerprint, issued_at, revoked_at).
- `DeviceCommand` (UNLOCK, PING, SYNC_KEYS, REBOOT; status QUEUED → SENT → ACKED → EXECUTED | FAILED | EXPIRED).
- `DoorEvent` (qbox, compartment, type OPEN_CONFIRMED | CLOSED_CONFIRMED | DOOR_LEFT_OPEN | FORCED_OPEN | TAMPER, device event id, device sequence number, occurred_at, received_at, token nonce if any). Unique on (qbox, device_event_id).
- `Evidence` (photo/clip, storage key, linked to door event / driver session / shipment, retention_until).

**Access control**
- `AccessToken` (purpose DELIVERY | PICKUP | OWNER_DEPOSIT | OWNER_COLLECT, qbox, compartment, shipment, nonce, key id, issued_to (driver session or user), expires_at, status ISSUED → USED | EXPIRED | REVOKED, used_at).
- `DriverSession` (qbox, started_at, ip/user agent hash, language, attempts, failed_attempts, locked_until, actions log).
- `OwnerApprovalRequest` (driver session, tracking number entered, snapshot evidence, status PENDING → APPROVED | REJECTED | EXPIRED).

**Shipments**
- `Shipment` with `direction` INBOUND | OUTBOUND | RETURN and `return_type` R1 | R2 | R3 (nullable).
  - Keep **three separate status fields**:
    - `lifecycle_status` — the business state (Section 5).
    - `carrier_status` — normalized carrier/tracking status.
    - `physical_status` — NOT_IN_QBOX | IN_QBOX | COLLECTED | PICKED_UP_FROM_QBOX, set only from door events.
  - Fields: owner account, origin (qbox / compartment / warehouse / external address), destination, parties (SHIPPER, CONSIGNEE snapshots), parcel (weight, dimensions, declared value, contents, flags COD / SIGNATURE_REQUIRED / DANGEROUS), carrier, service, AWB, carrier reference, label refs, nickname, our reference `QB…`.
  - Constraint: a tracking number + carrier can be active on only one Qbox at a time.
- `TrackingSubscription` (shipment, provider AFTERSHIP | CARRIER_DIRECT | MOCK, external id, status, last_polled_at, stale_at).
- `TrackingEvent` (shipment, provider, raw code, raw payload ref, normalized status, location, occurred_at, provider event id — unique).
- `PickupRequest` (carrier, pickup address/qbox, window start/end, carrier pickup reference, status REQUESTED → CONFIRMED → DRIVER_ASSIGNED → COMPLETED | MISSED | CANCELLED | FAILED, linked shipments M2M, rebook count).
- `ReturnAddress` (merchant saved return addresses + popular store return addresses).

**Commerce and money**: see Section 6.

**Carriers**: see Section 7.

**Platform**
- `AuditEvent`, `OutboxMessage`, `IdempotencyRecord`, `NotificationTemplate`, `NotificationLog`, `FeatureFlag` (or existing equivalent), `SystemSetting` (configurable policies: attempt limits, QR expiry, deposit deadline days, cancellation fees, retention days).

---

## 4. Permanent Qbox Identity QR and hardware endpoints

### 4.1 Identity code design

- `qbox_code`: 8 characters from an unambiguous alphabet (no 0/O/1/I/L), random, non-sequential, unique, with a check character to catch typos (e.g. `QB7K2M9A` style; keep the existing format if one already exists). It is **permanent for the life of the locker** and never reused.
- The printed QR encodes **only a URL**, never a secret: `https://{DRIVER_PORTAL_DOMAIN}/d/{qbox_code}?s={short_sig}`
  - `short_sig` = first 10 chars of base32(HMAC-SHA256(PRINT_KEY, qbox_code)). It lets the portal detect forged or tampered stickers (a sticker pointing at a code that fails the check is shown a warning and logged). The code alone still works when typed manually.
  - `DRIVER_PORTAL_DOMAIN` is configurable. The portal must show the official domain clearly so drivers can spot phishing stickers.
- **Scanning the Identity QR never opens a door.** It only opens the Driver Portal for that Qbox.

### 4.2 Device lifecycle

`MANUFACTURED → PROVISIONED → QA_PASSED → IN_STOCK → ALLOCATED → SHIPPED → INSTALLED → ACTIVE ⇄ SUSPENDED → RETIRED` (plus `QA_FAILED`, `RMA`). Transitions only through services, all audited. Ownership transfer is an explicit, audited action.

### 4.3 Factory endpoints (`/api/v1/factory/…`, factory roles only)

- `POST /batches/` — create a batch of N devices for a model; generates `qbox_code`s, serials and compartments from the model's layout.
- `GET /batches/`, `GET /batches/{id}/`
- `POST /devices/{id}/provision/` — registers the device public key / certificate (device generates its keypair; never send private keys from the server if avoidable; if the hardware cannot, generate a one-time provisioning secret shown once).
- `POST /devices/{id}/qa/` — record QA result per compartment (lock, sensors, camera reads test QR).
- `GET /devices/{id}/identity-qr/?format=svg|png|pdf` — the permanent QR artwork.
- `GET /batches/{id}/identity-qr-sheet/?format=pdf` — print-ready sheet for the whole batch: QR, `qbox_code` in large text, "Driver? Scan me" in Arabic + English + pictogram, short URL for manual entry. Vector output, high error-correction (level Q or H), quiet zone respected, size parameter in mm.
- `POST /devices/{id}/reprint/` — same code, new artwork, audited (for damaged stickers). Codes are never regenerated.
- Inventory endpoints: move to stock, allocate to order/account, mark shipped.

### 4.4 Device API (`/api/v1/devices/…`, device-authenticated only)

Authenticate each device with its credential (mTLS or signed requests with the device key; a request signature with timestamp + nonce to prevent replay). Design a `DeviceTransport` abstraction so MQTT can be added later without changing services; implement HTTPS now.

- `POST /devices/heartbeat/` — status, firmware, battery, door states, connectivity.
- `POST /devices/tokens/verify/` — device sends the scanned QR payload; server verifies and, if valid, returns UNLOCK for the specific compartment and marks the token as pending use.
- `POST /devices/events/` — batched door events with device sequence numbers; idempotent; out-of-order safe.
- `GET /devices/commands/` (poll) and `POST /devices/commands/{id}/ack/`.
- `GET /devices/keys/` — current access-token public keys (with `kid`) for offline verification.
- `POST /devices/offline-sync/` — tokens used offline (nonce list) and events captured offline.
- `POST /devices/evidence/` — upload URL request for clips/photos (pre-signed upload to private storage).

### 4.5 Access tokens (one-time QRs)

- Sign with **Ed25519**; include `kid` for key rotation. Keys in a secrets store; rotation command and grace period.
- Payload (compact, versioned): `v, kid, qbox_id, compartment_id, shipment_id, purpose, exp, nonce`. Encode as a compact signed string suitable for a QR (base45 or base64url).
- Single use: the nonce is burned on first successful use; a second scan is rejected, logged and alerted.
- Default expiry: Delivery QR → end of delivery day; Pickup QR → end of pickup window; Owner QR → 10 minutes. All configurable in `SystemSetting`.
- Offline: the device verifies the signature with the public key, keeps a local used-nonce list, and syncs later. Server reconciles conflicts (a nonce used twice → security incident).
- Every door opening notifies the owner and starts the evidence recording.

### 4.6 Device simulator (required)

Build `manage.py qbox_simulate_device` (and a Superadmin "Device simulator" page) that can act as a locker: heartbeat, verify a token, emit OPEN/CLOSED events, go offline, sync. All end-to-end tests use it. This is how the team tests full flows without hardware.

---

## 5. Unified state machines

Use these exact names everywhere (backend enums, frontend labels, docs). If the existing code uses different names (e.g. `AWAITING_DROPOFF`, `PICKED_UP`), migrate them with a data migration and keep a temporary alias in API output only if a client depends on it.

### 5.1 Inbound lifecycle

`REGISTERED → IN_TRANSIT → OUT_FOR_DELIVERY → DRIVER_VERIFIED → DELIVERED_TO_QBOX → COLLECTED`

Side states: `ATTEMPT_FAILED` (keep/renew Delivery QR), `AT_CARRIER_POINT`, `CARRIER_SAYS_DELIVERED` (no door event → "Not in your Qbox" + evidence report), `EXCEPTION`, `STALE` (auto-archive after inactivity, can re-activate), `CANCELLED` (allowed until OUT_FOR_DELIVERY), `NOT_ELIGIBLE` (COD / signature).

Rules:
- At OUT_FOR_DELIVERY: allocate the smallest free compartment that fits (expected size from customer input or history), reserve it, create the Delivery token (shown to a driver only after he enters the correct tracking ID), notify the customer.
- If the driver arrives before OUT_FOR_DELIVERY: force a live tracking refresh; if the tracking ID is registered to this Qbox and not delivered, issue the token anyway (default policy; owner can make it strict).
- Late or out-of-order carrier events must never move the lifecycle backwards after DELIVERED_TO_QBOX or COLLECTED. Store them; do not apply them.
- Stop paid tracking after DELIVERED_TO_QBOX (cost control).

### 5.2 Outbound lifecycle

`DRAFT → QUOTED → PENDING_PAYMENT → PAID → BOOKING → LABEL_READY → IN_QBOX → PICKUP_BOOKED → PICKED_UP_BY_CARRIER → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED`

Side states: `BOOKING_FAILED` (after retries → full automatic refund), `CANCELLATION_REQUESTED → CANCELLED`, `DEPOSIT_OVERDUE` (reminder, then auto-cancel with refund minus fee), `PICKUP_MISSED` (auto re-book), `EXCEPTION`, `RETURNED_TO_SENDER`, `NOT_CANCELLABLE` (after pickup — a guard, not a state).

Warehouse origin: `LABEL_READY → READY_FOR_HANDOVER → HANDED_OVER (= PICKED_UP_BY_CARRIER)` using the existing hand-over endpoint.

Qbox-to-Qbox (opted-in recipient token): when the consignee is a Qbox user, automatically create a linked recipient-side inbound record (or recipient view) so the destination Qbox gets compartment allocation, Delivery QR and collection, exactly like normal receiving. Keep sender identity masked as already implemented.

### 5.3 Return lifecycle

`RETURN_CREATED → (R1: AWB_ADDED | R2/R3: PENDING_PAYMENT → PAID → LABEL_READY) → IN_QBOX → PICKUP_BOOKED → PICKED_UP_BY_CARRIER → IN_TRANSIT → RETURN_DELIVERED`

R3 has no Qbox deposit on the customer side; it ends as an inbound delivery into the merchant's Qbox.

### 5.4 Carrier status normalization

Normalized set: `INFO_RECEIVED, IN_TRANSIT, OUT_FOR_DELIVERY, ATTEMPT_FAILED, AVAILABLE_FOR_PICKUP, DELIVERED, EXCEPTION, RETURNING, RETURNED, CANCELLED, UNKNOWN`. Mapping from raw provider codes lives in a DB table (`CarrierStatusMapping`: provider, carrier, raw code → normalized, editable in Superadmin). Unmapped codes → `UNKNOWN` + alert + visible in Superadmin.

---

## 6. Payments and money flow (platform collects, platform pays providers)

### 6.1 Principle

Qbox is the merchant of record for shipping services it sells. **Homeowners and merchants pay Qbox. Qbox pays carriers and other service providers.** These are two separate money flows, connected only through the ledger and reconciliation by AWB.

### 6.2 Payment provider abstraction

`PaymentGateway` interface (Moyasar is the first implementation; keep the existing verified flow):
`create_payment / create_invoice`, `fetch_payment`, `verify(payment, provider_payment)`, `refund(amount)`, `void`, `tokenize_card / charge_saved_card`, `parse_webhook`.
Keep: server-side verification of state, amount, currency and linkage; webhook secret check in constant time; dedupe by event id; async processing; reconciliation of initiated payments; expiry of abandoned ones.

Add:
- **Credit/wallet + card split payments:** if the card part fails or expires, the reserved wallet/credit amount is released automatically.
- **Saved cards** (Moyasar tokenization, explicit consent, list/delete endpoints) for weight adjustments and merchant auto-charge.
- **Refund model:** `Refund` (payment, amount, reason, status REQUESTED → PROCESSING → SUCCEEDED | FAILED, provider refund id, initiated_by). Partial refunds supported. Refund to original method, or to wallet if the user chooses.
- **Charge adjustments:** `ChargeAdjustment` (shipment, type WEIGHT_ADJUSTMENT | SURCHARGE | DAMAGE_FEE, carrier evidence, amount, status) charged to wallet or saved card; failure → account flag and collection workflow.
- **Remove legacy `payments/` shipment payment endpoints:** return `410 Gone` with an error code, then delete after one release. Keep only what the canonical flow needs.

### 6.3 Double-entry ledger (required)

Create a `ledger` app. All money movement creates balanced `JournalEntry` records (sum of debits = sum of credits, enforced). Entries are immutable; corrections are reversing entries.

Chart of accounts (minimum, extend as needed):
- Assets: `gateway_clearing:moyasar`, `bank:operating`, `carrier_prepaid:{carrier}`
- Liabilities: `customer_wallet:{account}`, `customer_order_liability` (unearned), `carrier_payable:{provider}`, `provider_payable:{provider}`, `vat_output_payable`, `refunds_payable`
- Revenue: `revenue:platform_fee`, `revenue:shipping_margin`, `revenue:return_fee`, `revenue:subscription`, `revenue:cancellation_fee`
- Expenses: `expense:payment_fees`, `expense:carrier_cost_variance`, `expense:tracking`, `expense:chargebacks`

Example postings (amounts in halalas, carrier cost 1700, customer shipping 2000, platform fee 100, VAT 315, total 2415):
1. Customer pays by card: Dr `gateway_clearing:moyasar` 2415 / Cr `customer_order_liability` 2415.
2. AWB created (service delivered/committed): Dr `customer_order_liability` 2415 / Cr `carrier_payable:smsa` 1700, Cr `revenue:shipping_margin` 300, Cr `revenue:platform_fee` 100, Cr `vat_output_payable` 315.
3. Gateway settles to bank (fee 48): Dr `bank:operating` 2367, Dr `expense:payment_fees` 48 / Cr `gateway_clearing:moyasar` 2415.
4. Qbox pays carrier invoice: Dr `carrier_payable:smsa` / Cr `bank:operating`.
5. Wallet top-up, wallet spend, refunds, booking failure, cancellation fee, weight adjustment and carrier invoice variance each get their own documented posting rule.

Write `docs/finance/POSTING_RULES.md` listing every event and its posting, and a test per rule. Add a nightly job that checks the trial balance and alerts if it does not balance.

### 6.4 Merchant wallet

Append-only wallet ledger (not a mutable balance field): top-up via Moyasar, spend, hold/release, refunds to wallet, statements. Optional auto top-up with a saved card. Optional credit limit for approved enterprise accounts (Superadmin setting).

### 6.5 Paying service providers (carriers and others)

- `ServiceProvider` (type CARRIER | TRACKING | NOTIFICATION | INSTALLER | OTHER, legal name, VAT number, bank details encrypted, payment terms, currency).
- `ProviderInvoice` + `ProviderInvoiceLine` (import CSV/XLSX now; API import later through the carrier adapter). Lines match to shipments by AWB.
- **Reconciliation engine:** for each line → MATCHED | AMOUNT_VARIANCE | WEIGHT_VARIANCE | UNKNOWN_AWB | DUPLICATE. Variance rules in `SystemSetting`: absorb under X halalas, otherwise create a `ChargeAdjustment` against the customer or open a dispute with the carrier.
- Per shipment store: quoted carrier cost, actual invoiced carrier cost, surcharges, payment fee, revenue lines, **gross margin**, `customer_payment_status`, `carrier_settlement_status` (UNSETTLED | SETTLED | DISPUTED).
- `PayoutBatch` (provider, invoices included, total, status DRAFT → PENDING_APPROVAL → APPROVED → PAID | CANCELLED). **Maker-checker:** the person who creates a batch cannot approve it. Payment execution is manual for now (finance enters bank transfer reference); keep a `PayoutRail` interface so a bank API can be added later.
- Support prepaid carrier balances as an alternative to invoice terms (`carrier_prepaid:{carrier}` account).

### 6.6 Tax invoices (ZATCA)

Create an `invoicing` app with an `EInvoicingProvider` interface. Every paid order issues a tax invoice (simplified for consumers, standard for VAT-registered merchants), every refund a credit note, every adjustment a debit note. Sequential, gap-free numbering per series; invoice hash chain; QR code field; PDF rendering in Arabic + English. Implement a `LocalInvoiceProvider` now; leave `ZatcaFatooraProvider` as a documented stub with configuration slots. Never delete or edit an issued invoice.

### 6.7 Pricing engine

- `RateCard` (carrier, service, version, valid_from/to, zones, weight bands, volumetric divisor, min charge) and `Surcharge` rules (fuel %, remote area, oversize, declared-value protection).
- `PricingPolicy` (Qbox markup rules by account type / volume tier, platform fee, return fee, discounts, promo codes).
- Quote calculation: chargeable weight = max(actual, volumetric) → carrier cost (from carrier rate API if the adapter supports it, else the rate card) → customer shipping price → platform fee → discounts → VAT → total. **Store every input and the rate card version on the quote** so any price can be reproduced.
- Quotes expire (default 15 min). Once checkout starts, the order locks the price; a quote that expires during an active payment is honoured.

---

## 7. Carrier integration framework (SMSA-ready, any-carrier-ready)

### 7.1 Adapter contract

Create `carriers/` with:

```python
class CarrierAdapter(Protocol):
    code: str                                  # "mock", "smsa", "aramex", ...
    def capabilities(self) -> CarrierCapabilities: ...
    def validate_address(self, addr: Address) -> AddressValidationResult: ...
    def get_rates(self, req: RateRequest) -> list[RateResult]: ...
    def create_shipment(self, req: CreateShipmentRequest) -> CreateShipmentResult: ...  # AWB, carrier ref, label
    def get_label(self, awb: str, fmt: LabelFormat) -> LabelResult: ...                  # PDF / ZPL
    def find_by_reference(self, our_reference: str) -> CreateShipmentResult | None: ...
    def cancel_shipment(self, awb: str) -> CancelResult: ...
    def book_pickup(self, req: PickupBookingRequest) -> PickupBookingResult: ...
    def cancel_pickup(self, pickup_ref: str) -> CancelResult: ...
    def track(self, awbs: list[str]) -> list[NormalizedTrackingEvent]: ...
    def verify_webhook(self, headers: dict, body: bytes) -> bool: ...
    def parse_webhook(self, headers: dict, body: bytes) -> list[NormalizedTrackingEvent]: ...
    def import_invoice(self, file_or_api_ref) -> list[ProviderInvoiceLineData]: ...
```

`CarrierCapabilities` declares: rates_api, cancel_before_pickup, cancel_after_pickup, pickup_api, pickup_windows, label_formats, multi_piece, cod, returns, webhooks, address_validation, max_weight, max_dimensions, serviceable cities, idempotency_supported. **Business services must check capabilities and fall back** (e.g. no rates API → rate card; no pickup API → manual pickup task in Superadmin; no webhook → polling).

All request/response types are carrier-neutral dataclasses/pydantic models. **No carrier-specific field may appear outside its adapter.**

### 7.2 Registry and configuration

- `Carrier` (code, name, active, adapter path, supported services).
- `CarrierAccount` (carrier, environment SANDBOX | PRODUCTION, encrypted credentials JSON, account number, is_default, optional owner account for merchant-specific sub-accounts).
- `CarrierService` (carrier, code, display names AR/EN, constraints, active).
- `CarrierCityMapping` (our normalized city → carrier city code/name).
- `CarrierStatusMapping` (Section 5.4).
- Adapters are resolved through a registry; adding a carrier = adapter class + config rows + mapping rows + tests. Write `docs/carriers/ADDING_A_CARRIER.md` with a checklist.

### 7.3 Reliability rules

- **Duplicate AWB protection:** always send our `QB…` reference as the carrier's reference field. On timeout or unknown result, call `find_by_reference` before retrying. A unique constraint on (carrier, AWB) and one active booking per shipment.
- Classify errors: `RetryableCarrierError` (timeout, 5xx, rate limit) vs `PermanentCarrierError` (invalid address, unserviceable, overweight) vs `AuthCarrierError` (alert ops immediately). Retries with exponential backoff + jitter, a circuit breaker per carrier account, and a manual-review queue.
- `CarrierApiCall` log: carrier, operation, request/response (PII-redacted), status code, duration, correlation id, shipment. Retention configurable.
- Webhooks: generic endpoint `POST /api/v1/carriers/webhooks/{carrier_code}/` → verify → store raw → dedupe → queue → normalize → apply. Polling fallback job for carriers without webhooks and for stale shipments.
- Labels stored in private storage, downloadable only by the owner (and Superadmin), with signed short-lived URLs.

### 7.4 Implementations to deliver now

1. **`MockCarrierAdapter` (complete).** Deterministic AWB generation, a generated PDF label (and ZPL text), rate calculation from a rate card, pickup booking with windows, cancel rules, and a **scenario system** (`success`, `timeout_then_success`, `invalid_city`, `booking_fails`, `pickup_missed`, `weight_adjustment`, `lost_in_transit`) selectable per shipment in non-production environments. A Superadmin "Carrier simulator" page can push tracking events for any AWB.
2. **`SmsaAdapter` (skeleton).** The class, configuration slots, city/status mapping table placeholders, and every method raising `CarrierNotConfigured` with TODO notes listing what must be confirmed from SMSA's API docs (endpoints, auth, reference field, label format, pickup API, cancellation rules, webhook signature). Contract-test file with fixtures to fill in once sandbox access exists.
3. **Tracking providers** behind the same idea: `TrackingProvider` interface with `AfterShipProvider` (skeleton with config), `CarrierDirectTrackingProvider` (uses the carrier adapter's `track`/webhooks — preferred for carriers Qbox has contracts with, to save AfterShip cost), and `MockTrackingProvider`. A routing rule chooses the provider per carrier.

### 7.5 Address and phone normalization

- Phone numbers → E.164 (`+9665XXXXXXXX`), validated.
- Saudi National Address: accept short address (e.g. `JEDA4321`) or full fields; store raw input and the resolved structured address (building number, street, district, city, postal code, additional number). `AddressResolver` interface with a manual/mock implementation now; a National Address API implementation later.
- City normalization table shared by all carriers.

---

## 8. Driver Portal (public, in Qbox-Frontend-Panel)

A separate public route group in the frontend (e.g. `/d/:qboxCode`), mobile-first, no login, fast on low-end Android phones, works on slow networks. Large buttons, high contrast, pictograms, language switcher (AR, EN, UR, HI, BN) with RTL for Arabic and Urdu. It must not load panel code or expose panel routes.

### 8.1 Backend endpoints (`/api/v1/driver/…`, public, rate-limited per IP + per Qbox)

- `GET /q/{qbox_code}/?s=` — starts a `DriverSession` (opaque session token in an HttpOnly cookie or response), returns Qbox display info only (no owner name, no address), sticker-check result, online status, available actions.
- `POST /q/{qbox_code}/deliver/` `{tracking_number, phone_last4?}` — checks: registered to this Qbox; not delivered; not COD/signature; Qbox online or offline-capable; compartment available; attempts not exceeded. Returns the Delivery QR payload + compartment label + expiry. Unknown tracking → offers `ask_owner`.
- `POST /q/{qbox_code}/ask-owner/` — creates an `OwnerApprovalRequest` (push to owner with tracking number + camera snapshot request). Driver polls `GET /approval/{id}/` for up to a configurable time (default 3 min). Approved → shipment auto-registered + Delivery QR issued.
- `POST /q/{qbox_code}/pickup/` `{awb}` — checks AWB belongs to this Qbox and is IN_QBOX/PICKUP_BOOKED (or RETURN equivalent). Returns the Pickup QR.
- `POST /q/{qbox_code}/wont-fit/` — releases the compartment; for multi-compartment Qboxes, tries the next larger free one and returns a new QR; otherwise records the event and notifies the customer.
- `GET /session/status/` — live status (waiting for scan → door open → door closed → done) via polling or SSE.
- Security: 5 failed tracking attempts → portal paused for 15 minutes for that Qbox + owner alert (both configurable); tokens are useless unless read by that Qbox's camera; every action audited.

### 8.2 Portal screens

1. Landing: Qbox code, "Deliver a package" / "Pick up a package", language switcher, sticker warning if the check fails.
2. Enter tracking ID / AWB: text field + "Scan barcode" (camera barcode scanning in the browser, with manual fallback).
3. QR screen: full-screen QR, "Hold your screen in front of the Qbox camera", screen wake-lock, brightness hint, countdown.
4. Live status: door opened → "Place the parcel and close the door" → closed → "Delivered — thank you" (or "Picked up").
5. Errors and fallbacks: not registered → Ask the owner; won't fit; Qbox offline; locked out; expired.
6. "Deliver another package" loop.

---

## 9. Panels (in Qbox-Frontend-Panel)

Follow the existing design system, routing, auth, API client and state management. Every list has search, filters, pagination, sorting and CSV export. Every money value is formatted from halalas. Every destructive or financial action requires confirmation and is audited. Role-based route guards and hidden actions for unauthorized roles (the backend still enforces permissions).

### 9.1 Roles

- Superadmin: `SUPER_ADMIN`, `OPS_AGENT`, `FINANCE`, `FINANCE_APPROVER`, `SUPPORT`, `READ_ONLY`.
- Factory: `FACTORY_ADMIN`, `FACTORY_OPERATOR`, `QA_INSPECTOR`.
- Merchant: `MERCHANT_OWNER`, `MERCHANT_ADMIN`, `MERCHANT_SHIPPING`, `MERCHANT_RECEIVING`, `MERCHANT_FINANCE`, `MERCHANT_VIEWER`.
- Homeowner (API only): `OWNER`, `FAMILY_MEMBER`.

### 9.2 Superadmin panel

- **Dashboard:** shipments by state, stuck-state alerts, booking success per carrier, payment success, webhook lag, online/offline lockers, revenue and gross margin.
- **Shipments:** search by reference/AWB/tracking/phone; detail with three status tracks, timeline (carrier events + door events + payments + audit), evidence viewer, actions (re-trigger booking, manual state override with mandatory reason, cancel/refund, re-book pickup, regenerate label).
- **Disputes & evidence:** "carrier says delivered — not in Qbox" cases, evidence report export (PDF).
- **Fleet:** lockers, compartments, health, firmware, commands (unlock with reason — audited and notified to owner), offline sync conflicts, security incidents.
- **Carriers:** carriers, accounts (credentials masked, test connection button), services, city mappings, status mappings (with unmapped-codes inbox), rate cards (versioned editor with preview quote), circuit-breaker status, API call log viewer.
- **Pricing:** pricing policies, fees, discounts/promo codes, quote calculator.
- **Finance:** payments, refunds (approval above a threshold), adjustments, wallets, ledger explorer, trial balance, provider invoices import + reconciliation screen, payout batches (maker-checker), tax invoices / credit notes.
- **Accounts:** homeowners, merchants, members, KYC/VAT details, credit limits, blocks.
- **Settings:** `SystemSetting` editor (QR expiry, attempt limits, deadlines, fees, retention), notification templates (AR/EN), feature flags.
- **Simulators (non-production only):** device simulator, carrier simulator, payment test helpers.
- **Audit log** viewer.

### 9.3 Factory panel

Batches (create, progress), device list with lifecycle, provisioning screen, QA checklist per compartment, **Identity QR print** (single + batch PDF sheet, size selection, reprint with reason), inventory (stock, allocate, ship), RMA intake.

### 9.4 Merchant panel

- **Overview:** inbound today, outbound pending deposit/pickup, wallet balance, alerts.
- **Qboxes & compartments:** live compartment view (available/reserved/occupied), reservations, open a compartment (owner deposit/collect token), door history with evidence.
- **Receiving:** add tracking (single + **CSV bulk import** with validation report + API key for programmatic import), list with filters, detail with timeline, COD/signature warnings, approve driver "ask the owner" requests.
- **Sending:** create shipment (recipient with saved address book, National Address lookup, parcel presets S/M/L/custom, declared value), quotes comparison by carrier/service, checkout (wallet / card / split), label print (PDF, ZPL), choose origin compartment or warehouse, deposit instructions, pickup schedule (grouped daily pickup), bulk create from CSV.
- **Returns:** R1 add return AWB, R2 create return label, R3 create merchant-paid returns for their customers (send label by SMS/WhatsApp link), saved return addresses.
- **Wallet & billing:** top-up, saved cards, transactions, tax invoices and credit notes download, adjustments with carrier evidence.
- **Team:** invite members, roles.
- **Developers:** API keys (scoped, rotatable), outgoing webhook endpoints with event selection, signing secret and delivery log (design now; the events catalogue documented).
- **Reports:** volumes, spend, returns, pickup performance; export.

---

## 10. Notifications

`NotificationService` with channels push, SMS, WhatsApp, email behind a `NotificationProvider` interface (mock implementation now). Templates in AR/EN, per-event, per-channel, with user preferences. Required events: tracking added, out for delivery (Qbox ready), delivered to Qbox (with photo), door opened (any reason), carrier says delivered but not in Qbox, owner approval request, payment succeeded/failed, label ready, deposit reminder, pickup booked/missed/completed, delivered, refund issued, adjustment charged, low wallet balance, device offline, door left open.

---

## 11. Testing requirements

- Unit tests for every service, state transition, pricing rule, posting rule and adapter.
- **End-to-end scenario tests** (backend) using the Mock carrier, Mock tracking, Moyasar test doubles and the device simulator:
  1. Inbound happy path → DELIVERED_TO_QBOX → COLLECTED; carrier "Delivered" before door event does not deliver.
  2. Inbound unknown tracking → ask owner → approve → delivered.
  3. Wrong tracking 5× → lockout.
  4. Outbound homeowner: quote → order → card payment → AWB → deposit → pickup booked → pickup QR → picked up → delivered; ledger balances; invoice issued.
  5. Outbound merchant from Qbox Business with wallet payment and grouped daily pickup.
  6. Split wallet + card where card fails → wallet hold released.
  7. Booking timeout then success → exactly one AWB.
  8. Booking permanent failure → BOOKING_FAILED → full refund → credit note.
  9. Cancel before pickup → carrier cancel → refund minus fee.
  10. Weight adjustment from carrier invoice → charge saved card → debit note.
  11. Carrier invoice reconciliation with variances → payout batch → maker-checker approval → paid.
  12. Returns R1, R2, R3.
  13. Offline locker uses token offline, syncs later; reused nonce flagged.
  14. Qbox-to-Qbox send to opted-in recipient.
- Webhook tests: invalid secret, duplicate event, out-of-order events.
- Permission tests for every endpoint and role.
- Frontend: component tests for critical forms; Playwright (or the project's tool) e2e for Driver Portal deliver/pickup, merchant send + checkout, factory QR print, superadmin refund approval.

---

## 12. Delivery phases (do them in order)

For each phase: implement backend + migrations + tests + OpenAPI + frontend screens + docs, update `PROGRESS.md`, and list acceptance results.

| Phase | Scope | Acceptance |
|---|---|---|
| 0 | Inspect both repos; write `CURRENT_STATE.md`, gap list, ADR for target architecture; set up test/lint/CI commands | Documents written; plan in `PROGRESS.md` |
| 1 | Platform foundations: AuditEvent, Outbox (if missing/incomplete), Idempotency for all POSTs, SystemSetting, roles/permissions, state-machine framework; unify status names with data migration | All existing tests pass; transition guard tests |
| 2 | Hardware: DeviceModel, Batch, Qbox lifecycle, Compartments, Identity QR generation + print endpoints, device auth + device API, simulator; Factory panel | Factory can create batch, provision, QA and print a QR sheet; simulator heartbeats |
| 3 | Access tokens (Ed25519, rotation, offline keys), DoorEvent ingestion, Evidence, owner deposit/collect tokens | DELIVERED_TO_QBOX only via door events; reuse rejected |
| 4 | Carrier framework: adapter contract, registry, config models, mappings, CarrierApiCall log, reliability rules, MockCarrierAdapter complete, SmsaAdapter skeleton, TrackingProvider abstraction, address/phone normalization | Full outbound runs on Mock; `ADDING_A_CARRIER.md` written |
| 5 | Inbound flow complete (Section 5.1) + Driver Portal backend + Driver Portal frontend | E2E scenarios 1–3 pass; portal works on mobile |
| 6 | Payments hardening: gateway interface, split payments, saved cards, Refund, ChargeAdjustment, legacy removal | Scenarios 6, 8, 9, 10 pass |
| 7 | Ledger + posting rules + wallet + invoicing (local provider, ZATCA stub) | Trial balance check passes in all scenarios |
| 8 | Outbound flow complete: pricing engine, PickupRequest, deposit deadline, pickup re-booking, warehouse path kept, Qbox-to-Qbox | Scenarios 4, 5, 7, 14 pass |
| 9 | Returns R1/R2/R3 | Scenario 12 passes |
| 10 | Provider settlement: ServiceProvider, invoice import, reconciliation, payout batches with maker-checker | Scenario 11 passes |
| 11 | Merchant panel complete (Section 9.4) | Merchant e2e passes |
| 12 | Superadmin panel complete (Section 9.2), notifications, simulators, dashboards | Superadmin e2e passes |
| 13 | Hardening: security review, rate limits, PII redaction, retention jobs, observability, load test of webhooks and portal, docs review | Checklist in `docs/RELEASE_CHECKLIST.md` complete |

---

## 13. Definition of done (whole project)

- Every flow in the business document runs end-to-end in a local/staging environment using Mock carrier, Mock tracking, Moyasar test mode and the device simulator.
- Adding SMSA (or any carrier) requires only: implementing its adapter, filling config/mapping rows, and passing its contract tests — **no change to shipments, payments, ledger, portal or panels.**
- Every money movement is in the ledger, balanced, and traceable from customer payment to provider payout by AWB.
- No door opens without a valid single-use signed token read by the locker; every opening is audited, notified and has evidence.
- OpenAPI docs, ADRs, posting rules, carrier guide and runbooks are complete and accurate.

## 14. Things you must NOT do

- Do not accept prices, totals, carrier costs or statuses from clients.
- Do not let a carrier status set DELIVERED_TO_QBOX.
- Do not put secrets in a QR, in logs or in the repository.
- Do not add carrier-specific fields to shared models or APIs.
- Do not mutate balances directly; post ledger entries.
- Do not edit or delete issued invoices, journal entries or audit events.
- Do not call real SMSA/AfterShip/ZATCA/bank endpoints or invent their API details. Leave clear TODOs instead.
- Do not skip tests or mark work done with failing tests.

---

## 15. Owner decisions (override earlier sections)

Recorded 2026-10-04 after Phase 0 (`PROGRESS.md`, `Qbox-Backend/docs/adr/0001-evolve-existing-platform-to-master-prompt.md`).
Where this section conflicts with Sections 0–14, this section wins.

1. **Status names.** Wire status names stay as they are in the existing code (`Shipment.Status`). The names in Section 5
   are display labels plus a documented mapping (`Qbox-Backend/docs/architecture/CURRENT_STATE.md` §5). Missing states
   are added additively. Section 5's "migrate them with a data migration" does not apply.
2. **`qbox_code`.** Stays the existing immutable 7-character `ABC-234` format. Only the `?s=` HMAC sticker check from
   Section 4.1 is added.
3. **Active tracking uniqueness.** The existing global rule (one active registration per normalized tracking number,
   regardless of Qbox) is accepted; it is stricter than Section 3's per-Qbox constraint.
4. **Release order.** Release R (legacy removal) ships first. Phase 1+ work happens on a new branch that is rebased on
   `feat/shipment-platform-phase2` regularly and is not merged until Release R is deployed.
