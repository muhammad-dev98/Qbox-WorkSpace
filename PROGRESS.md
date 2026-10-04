# QBox master prompt — progress

Spec: workspace `QBOX_AGENT_MASTER_PROMPT.md` (§15 owner decisions override earlier sections).
Repos: `Qbox-Backend` (Release R branch `feat/shipment-platform-phase2`; Phase 1+ branch `feat/master-prompt-phase1`), `Qbox-Frontend-Panels` (`main` + uncommitted work by another author).
Phase 0 documents: `Qbox-Backend/docs/architecture/CURRENT_STATE.md`, `Qbox-Frontend-Panels/docs/CURRENT_STATE.md`,
`Qbox-Backend/docs/adr/0001-evolve-existing-platform-to-master-prompt.md`.

## Phase status

| Phase | State |
|---|---|
| 0 Inspect, current state, gap list, ADR, plan | ✅ documents written · test/lint/CI setup moved to Phase 1 (backend has no lint and no CI test job) |
| Baseline | pending: full backend suite on a fresh PostgreSQL DB at `598712bd` |
| Release R hotfixes | pending owner approval of each diff (see below) |
| 1–13 | not started |

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
| a | Release consumed credit (with ledger reversal) when the card part of a split payment fails or expires (`shipping/services/orders.py` FAILED and expiry paths) | not started |
| b | Replace floored, hardcoded VAT in `commerce/services.py` with `shipping/services/vat.py` | not started |

## Frontend rules for the uncommitted work

The author commits it to their own branch. When it lands: revert the sessionStorage token store (memory + httpOnly
refresh cookie per ARCHITECTURE.md) and replace the `/api/v1`-stripping interceptor with a correct base URL.

## Open questions (owner)

1. **Hardware approval** of locker-device-v1 is still pending; v2 (offline Ed25519) needs the hardware team too.
2. Carried over: accountant sign-off on VAT mode/revenue recognition; SMSA/AfterShip/Moyasar staging credentials.

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
