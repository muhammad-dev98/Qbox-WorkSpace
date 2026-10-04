# QBox master prompt — progress

Spec: workspace `QBOX_AGENT_MASTER_PROMPT.md` (§15 owner decisions override earlier sections).
Repos: `Qbox-Backend` — work happens on local **`main`** (owner, 2026-10-04: Release R merged into local main; **never push main: it deploys**). `Qbox-Frontend-Panels` — `main` carries another author's uncommitted work, so frontend work is on branches.
Phase 0 documents: `Qbox-Backend/docs/architecture/CURRENT_STATE.md`, `Qbox-Frontend-Panels/docs/CURRENT_STATE.md`,
`Qbox-Backend/docs/adr/0001-evolve-existing-platform-to-master-prompt.md`.

## Phase status

| Phase | State |
|---|---|
| 0 Inspect, current state, gap list, ADR, plan | ✅ documents written · test/lint/CI setup moved to Phase 1 (backend has no lint and no CI test job) |
| Baseline | ✅ 2026-10-04, fresh PostgreSQL 16 (throwaway container), `598712bd` (= backend `main` code after the local Release R merge): **Ran 992, FAILED (errors=1, skipped=9, expected failures=1)**, 29 min, `--parallel 4`. The one error is a date time-bomb (`factory_ops…test_customer_is_notified_on_schedule` hardcoded 2026-10-01); fixed on `main` in `900d869e`. `check` clean, `makemigrations --check` no changes. |
| Release R hotfixes | a, b, c ready on their own branches, **awaiting owner approval** (see below) |
| 1 Foundations | ✅ backend `main` `347f141d`…`9de2ce4c`. Gate at `0c9b67db` (fresh DB, minimal CI env): 1040 ran, 7 failed — 6 from missing MQTT dummy creds in the CI env, 1 idempotency gap; both fixed in `9de2ce4c`, affected tests re-run OK |
| 1b FE merchant minimal fix | ✅ frontend branch `fix/merchant-canonical-shipments` (5 commits; lint/typecheck/34 unit/build/30 e2e pass) |
| 2 Hardware | ✅ backend `727870a3`…`7da03ce8`; FE branch `feat/factory-identity-stickers` (7 commits; lint/typecheck/33 unit/build/87 e2e pass). Gate at `e87fc7bc` (fresh DB, CI env, check + makemigrations + ruff clean): **1075 ran, 1 failure** (status-write guard vs derived compartment status, fixed in `7da03ce8`); later commits verified with factory_ops (301 OK) and the guard tests |
| 3 Access tokens v2 | contract proposal written (`contracts/api/locker-device-v2.md`), awaiting hardware approval; no code |
| 4–13 | not started |

## Key finding

Most of the master prompt already exists (backend milestones M0–M8, ~990 passing tests). The phases below are
**re-scoped to the remaining gaps**; numbering follows the master prompt so acceptance criteria still line up.

## Re-scoped plan (backend unless marked FE)

| Phase | Remaining work |
|---|---|
| 1 Foundations | ruff config + CI workflow running the suite on PostgreSQL; central `AuditEvent` (actor, IP, UA, correlation id); DB-backed `SystemSetting` with env fallback; shared transition helper for Pickup, OpsTask, Order, Payment, Refund, AccessSession, Settlement + test forbidding undeclared transitions / raw status writes; Idempotency-Key on remaining POSTs + 24 h cleanup job; outbox jitter; platform roles (OPS_AGENT, FINANCE, FINANCE_APPROVER, SUPPORT, READ_ONLY) and merchant sub-roles; encrypt or stop storing legacy `PaymentMethod.gateway_payment_token` (plaintext); move the SPL API key out of the request URL; remove `drf-yasg` if nothing depends on it |
| 1b FE merchant minimal fix | move merchant shipments list / detail / create off the 410 routes to the canonical `/api/v1/shipments/` API (full merchant panel stays in Phase 11) |
| 2 Hardware | **first:** ADR 0002 + external identity sticker = `https://qbox.sa/d/{qbox_code}?s={sig}` labelled with `qbox_code`, "Driver? Scan me" AR/EN + pictogram; AES-GCM device-token QR becomes provisioning/installation-only. Then DeviceModel compartment layouts (HOME 1 / BUSINESS 4 / PRO n); **Compartment** model + smallest-fit allocation replacing `compartment_key="door"`; sticker `?s=` HMAC + warning; identity-QR SVG + batch sheet PDF + audited reprint; per-compartment QA; `qbox_simulate_device` command · FE factory: QR sheet, reprint, RMA |
| 3 Access tokens v2 | write `contracts/api/locker-device-v2.md` now as a proposal; implement only after hardware approval; Phases 2 and 4 do not wait for it. Ed25519 tokens with `kid`, rotation command, `/devices/keys/`, offline-sync + nonce-reuse incidents, batched door events, HTTPS command poll/ack, FORCED_OPEN/TAMPER, evidence upload + retention; `DeviceTransport` abstraction |
| 4 Carriers | adapter methods validate_address, cancel_pickup, verify/parse_webhook, import_invoice; full capabilities object; config-driven registry; `CarrierStatusMapping` + `CarrierCityMapping` models (+ unmapped inbox); auth error class, jitter, circuit breaker, `CarrierApiCall` log; generic `/carriers/webhooks/{code}/`; MOCK scenario system; signed label URLs; `AddressResolver` + city aliases |
| 5 Inbound + portal | ask-owner (`OwnerApprovalRequest`), wont-fit, session status, NOT_ELIGIBLE (COD/signature), ATTEMPT_FAILED, AT_CARRIER_POINT, stateful `DriverSession` · FE: new `apps/driver-portal` (5 languages, RTL, QR screen, wake-lock, barcode scan) |
| 6 Payments | single gateway interface (drop unused `financial/providers.py`); saved cards (encrypted token, consent); refund-to-wallet; `ChargeAdjustment`; legacy `/payments/` routes → 410 |
| 7 Ledger / wallet / invoicing | `POSTING_RULES.md` + test per rule; reversal entries; nightly trial balance; wallet top-up, holds, statements, credit limit; `invoicing` app (gap-free series, hash chain, QR, AR/EN PDF, credit/debit notes, ZATCA stub) |
| 8 Outbound | versioned rate cards, min charge, surcharges, tiers, return fee, promo codes, value snapshot on quote; DEPOSIT_OVERDUE; PICKUP_MISSED + auto rebook |
| 9 Returns | R3 merchant-paid; `ReturnAddress`; `return_type` field |
| 10 Settlement | `ServiceProvider`; XLSX import; WEIGHT_VARIANCE + variance rules; per-shipment margin; `PayoutBatch` with maker-checker; `PayoutRail`; prepaid carrier balance |
| 11 FE Merchant | move shipments to canonical API; receiving, sending, checkout, labels, returns, wallet, invoices, team, developers, reports |
| 12 FE Superadmin + notifications | carriers, pricing, finance, settings, simulators, disputes, fleet; notification provider interface, AR templates, preferences |
| 13 Hardening | security review, retention jobs, JSON logs, load tests, `docs/RELEASE_CHECKLIST.md` |

## Release R hotfixes (proposed; each diff shown to the owner before commit)

| # | Fix | State |
|---|---|---|
| a | Return consumed credit when the card part of a split payment fails or expires; FAILED status was never persisted (rolled back with the error) — fixed too; retry re-consumes credit; late success re-applies or refunds. No ledger reversal needed (credit usage is journaled only at payment). D54 | `hotfix/release-r-credit-release` `3d3a3192` · shipping+commerce+financial Ran 125 OK |
| b | Commerce product quote VAT: shared half-up rule instead of floor + hardcoded rate | `hotfix/release-r-commerce-vat` `68d0c5ba` · Ran 120 OK |
| c | Payment verified after its order was cancelled was kept (order flipped back to PAID; D20 orphan refund unreachable) | `hotfix/release-r-orphan-payment` `f3f2dd0a` · regression test fails without fix · Ran 118 OK |

On approval: cherry-pick onto `feat/shipment-platform-phase2`, then merge into `main` (main already has c's fix via the state machines; a will conflict lightly with the Phase 1 state-machine edits in `orders.py`).

## Frontend rules for the uncommitted work

The author commits it to their own branch. When it lands: revert the sessionStorage token store (memory + httpOnly
refresh cookie per ARCHITECTURE.md) and replace the `/api/v1`-stripping interceptor with a correct base URL.

## Findings that need the owner (not code)

1. **Secrets in git history (backend):** older commits of `.env.prod` (e.g. `ec246802`, `0322465b`) contain non-empty `SECRET_KEY`, `MOYASAR_SECRET_KEY`, `MOYASAR_WEBHOOK_SECRET`, WhatsApp `ACCESS_TOKEN`, `SPL_API_KEY`, `EMQX_DASHBOARD_PASSWORD`. The repo is on GitHub. Rotate all of them; purging history is a separate, destructive decision.
2. **VPS (read-only check 2026-10-04):** deployed `main` `1312ecfa` (Release R not deployed), 0 pending migrations, all containers healthy, Celery 1664/1664 tasks OK in 2 h, 5/6 lockers online, only DisallowedHost scanner errors. **`DEBUG=True` with `QBOX_REAL_CUSTOMER_DATA` unset is still live (D29).** Untracked private keys sit in the VPS repo directory (`emqx/certs/client-key.pem`, `client.key`).
3. **Door sensing (hardware):** the hardware docs say the second solenoid wire reports `verified_state=UNKNOWN`; DELIVERED_TO_QBOX depends on CLOSED_CONFIRMED, so v1 already relies on door sensing the hardware may not have (v2 proposal Q5).
4. Portal throttling uses `REMOTE_ADDR`; confirm nginx sets the real client IP (otherwise all drivers share one source). Phase 13.

## Open questions (owner)

1. **`QBOX_COMPARTMENT_SHARING`** default `allow` keeps Qbox Home accepting several parcels behind its one door; `strict` = one parcel per compartment (Home then accepts one at a time). ADR 0004.
2. Compartment inner dimensions and multi-compartment `component_key`s are placeholders until the hardware team confirms (Business/Pro hardware).
3. Owner code TTL: backend 30 min vs master prompt 10 min (v2 Q-B2). Kept 30, now a runtime setting.
4. **Hardware approval** of locker-device-v1 is still pending; v2 (offline Ed25519) needs the hardware team too.
5. Carried over: accountant sign-off on VAT mode/revenue recognition; SMSA/AfterShip/Moyasar staging credentials.

## Decisions log

- 2026-10-04 Phase 0: evolve existing platform (ADR 0001, accepted).
- 2026-10-04 Owner: keep current shipment status names on the wire; master-prompt names are labels + mapping; missing states added additively.
- 2026-10-04 Owner: keep the 7-char `ABC-234` `qbox_code`; add only the `?s=` HMAC sticker check.
- 2026-10-04 Owner: Release R ships first. Phase 1+ work on a new branch off `feat/shipment-platform-phase2`; not merged until Release R is deployed.
- 2026-10-04 Owner: global unique active tracking (stricter than per-Qbox) accepted.
- 2026-10-04 Owner: Phase 1+ branch is rebased on `feat/shipment-platform-phase2` regularly.
- 2026-10-04 Owner: identity sticker carries only the portal URL + `?s=`; AES-GCM device QR is provisioning-only (ADR 0002, Phase 2 start).
- 2026-10-04 Owner: minimal FE merchant fix (off 410 routes) runs between Phase 1 and Phase 2.
- 2026-10-04 Owner: locker-device-v2 is written as a proposal now; implemented only after hardware approval.
- 2026-10-04 Owner: continue everything on backend `main` (Release R merged locally, nothing pushed).
- 2026-10-04 drf-yasg kept: 61 files / 325 call sites feed drf-spectacular through it (ADR 0003).
- 2026-10-04 SPL key: `SPL_API_KEY_LOCATION` query (default, current SPL behaviour) or header once SPL confirms; never logged.
- 2026-10-04 New app named `platform_core` (the hardware runtime already has `qbox_platform`).
- 2026-10-04 Idempotency-Key stays optional (existing mobile clients) but every canonical state-changing POST honours it.
- 2026-10-04 qbox_codes keep being generated at device self-registration, not pre-generated per batch (ADR 0004).
