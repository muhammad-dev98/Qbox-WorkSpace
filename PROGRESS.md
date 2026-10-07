# QBox master prompt — progress

Spec: workspace `QBOX_AGENT_MASTER_PROMPT.md` (§15 owner decisions override earlier sections).
Phases spec: `QBOX_PHASES_3_TO_13_PROMPT.md` (overrides the master prompt where they differ).
Repos: `Qbox-Backend` — **work directly on `main`** (owner decision 2026-10-05, rules below). `Qbox-Frontend-Panels` — `main` carries another author's uncommitted work, so frontend work stays on branches until the owner says otherwise.

## Rules for backend `main` (owner, 2026-10-05) — every push deploys to the VPS, which has real customer data

1. Commit on local `main` in small, logical commits. The pre-push hook stays; use `QBOX_ALLOW_PUSH_TO_MAIN=1` only when rule 2 is met.
2. Push only when the full VPS gate (check, makemigrations, ruff, full suite on a fresh DB) passed for the **exact commit** being pushed. Never push with a failing test. About one push per finished phase or fix.
3. Before a push that contains migrations: `pg_dump` production on the VPS to `/root/backups/<date>-<commit>.sql.gz` and confirm the size. Migrations backward compatible (additive first, no column drops in the same release).
4. After every push: wait for the deploy, check health/live, health/ready, 0 pending migrations, web/worker/beat logs for 15 minutes, smoke-test the new endpoints; report.
5. A bad deploy: `git revert`, gate, push. Never force-push or rewrite `main`.
6. Frontend stays on branches until the other author's uncommitted frontend `main` files are committed (owner will say).

Latest full status: `docs/reports/STATUS_2026-10-07.md` (verified 2026-10-07).

## How gates run — SUPERSEDED 2026-10-05: tests must NOT run on the VPS any more

The VPS gates below triggered Hostinger's 20% CPU cap and a production outage on 2026-10-05. `/root/qbox-ci` was removed.
Gates move to GitHub Actions once `gh` is logged in on this machine. The owner runs every push to `main`.

Historical method:

Per run the branch is uploaded with `git archive` to `/root/qbox-ci/runs/<name>` on the VPS and `/root/qbox-ci/run-gate.sh <run-dir> 2`
runs: `check`, `makemigrations --check`, ruff (repo gate + strict list), full suite `--parallel 2` on a **fresh** test database
(`qbox_ci_<run>_test`) in the existing `qbox-test-db` container, capped at 1.5 CPU / 3 GB so production keeps headroom (VPS has 2 cores).
Image `qbox-ci-base` = the dev image + test tools (arabic-reshaper, python-bidi, ruff 0.14.0, tblib). Env: `/root/qbox-ci/env.base` (chmod 600, CI-only values).
Never touches `/var/www/Qbox-Back-End`. A full run takes ~37 min.
Phase 0 documents: `Qbox-Backend/docs/architecture/CURRENT_STATE.md`, `Qbox-Frontend-Panels/docs/CURRENT_STATE.md`,
`Qbox-Backend/docs/adr/0001-evolve-existing-platform-to-master-prompt.md`.

## Phase status

| Phase | State |
|---|---|
| 0 Inspect, current state, gap list, ADR, plan | ✅ documents written · test/lint/CI setup moved to Phase 1 (backend has no lint and no CI test job) |
| Baseline | ✅ 2026-10-04, fresh PostgreSQL 16 (throwaway container), `598712bd` (= backend `main` code after the local Release R merge): **Ran 992, FAILED (errors=1, skipped=9, expected failures=1)**, 29 min, `--parallel 4`. The one error is a date time-bomb (`factory_ops…test_customer_is_notified_on_schedule` hardcoded 2026-10-01); fixed on `main` in `900d869e`. `check` clean, `makemigrations --check` no changes. |
| Release R hotfixes | approved; a `b7605b4e`, b `68d0c5ba`, c `d9945518` pushed on their branches (off `598712bd`), one PR each; merge forward into integration after Release R is deployed |
| 1 Foundations | ✅ backend `main` `347f141d`…`9de2ce4c`. Gate at `0c9b67db` (fresh DB, minimal CI env): 1040 ran, 7 failed — 6 from missing MQTT dummy creds in the CI env, 1 idempotency gap; both fixed in `9de2ce4c`, affected tests re-run OK |
| 1b FE merchant minimal fix | ✅ frontend branch `fix/merchant-canonical-shipments` (5 commits; lint/typecheck/34 unit/build/30 e2e pass) |
| 2 Hardware | ✅ backend `727870a3`…`7da03ce8`; FE branch `feat/factory-identity-stickers` (7 commits; lint/typecheck/33 unit/build/87 e2e pass). Gate at `e87fc7bc` (fresh DB, CI env, check + makemigrations + ruff clean): **1075 ran, 1 failure** (status-write guard vs derived compartment status, fixed in `7da03ce8`); later commits verified with factory_ops (301 OK) and the guard tests |
| Phase 1–2 re-gate | ✅ `19065122` (`feat/master-phases-1-2`), fresh DB: **Ran 1076, OK** |
| 3 Access tokens v2 | contract proposal written (`contracts/api/locker-device-v2.md`), awaiting hardware approval; no code |
| 4 Carriers | ✅ `phase/4-carriers` `04fd004c` (ADR 0007). **VPS gate 2026-10-05: Ran 1141, OK (skipped 23, expected failures 1), 2038 s**; check / makemigrations / ruff clean. `integration/master-phases` fast-forwarded to it |
| 6 Payments | ✅ live (ADR 0008). Gate `bc371655`: Ran 1160 OK; strict lint failed on 2 lines, fixed `b7037ad2`. Moyasar void/tokenize/saved-card charge are stubs until Moyasar confirms the APIs. Credit-hold overlap with hotfix a: none needed |
| §1 Hardware reality | `phase/hw-reality` (on Phase 6): capability flags, `plate_number` + one code lookup (ADR 0005), printed-QR check + unverified-plates report + plate order sheet, single-door rules (occupancy, Qbox full / won't fit, collection confirmation, pickup warnings + owner block policy), single door always allocated (ADR 0004 amended) · ✅ backend live · FE `feat/factory-plates-single-door` pushed, not merged (2026-10-07 re-check: lint / typecheck / 56 unit / build pass) |
| `main` gate 2026-10-05 | owner merged the phase chain into `main` (`45ea9399`, deployed; tree = `phase/3-door-proof` `2dacdd44`). VPS gate: **Ran 1208, 4 failures + 2 errors** — 3 root causes, incl. a live 500 on `confirm-in-qbox` (FOR UPDATE on a nullable join). Fixed in `1bdca40a`: full gate Ran 1208 OK; pushed and deployed. Deploy check of `45ea9399`: healthy, 0 pending migrations, no errors, new beat jobs run |
| 3 (no firmware) | ✅ in `main`: proof levels, driver door-closed, owner confirmation, SecurityIncident + back office, batched events (provisional, accepted by owner), token_format (ADR 0009). Remainder waits for hardware approval |
| Release R hotfixes on `main` | cherry-picked onto `1bdca40a` (local, not pushed): b VAT; c repair command + audit (c's fix and test were already in `main` via Phase 1); a credit release + 2150 holds, merged through the Phase 1 state machines (no raw status writes). Credit-hold overlap with Phase 6: none needed — adjustment orders carry no credit and credit-paid adjustments post immediately. **Production dry run of `repair_orphan_payment_postings` (read-only session): affected orders 0.** No migrations |
| 5 Inbound + portal (backend) | ✅ live in `cda3b693` (ADR 0010): new inbound states, late arrival, owner second factor, portal sessions, ask-owner. **Only a targeted 74-test run, no full gate** — run one on GitHub. Portal app (FE) waits for frontend `main` cleanup |
| Production 2026-10-07 | `origin/main` = VPS = `c384f7c3`; health 200, 0 pending migrations, 0 app errors in 24 h; **DEBUG=true** still |
| 7–13 | not started |

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

## Release R hotfixes (approved 2026-10-05; Release R is on `main`, so they go to `main` next)

| # | Fix | State |
|---|---|---|
| a | Return consumed credit when the card part of a split payment fails or expires (+ FAILED status persisted). Owner: credit holds journaled on `2150-CUSTOMER-CREDIT-HOLDS` and reversed on release; audit event (`AUTOMATIC_REFUND`) for every automatic refund | `hotfix/release-r-credit-release` `b7605b4e` |
| b | Commerce product quote VAT: shared half-up rule instead of floor + hardcoded rate | `hotfix/release-r-commerce-vat` `68d0c5ba` · Ran 120 OK |
| c | Payment verified after its order was cancelled is refunded (was kept). `repair_orphan_payment_postings` command for orders already hit (dry run by default; `--commit` needs `QBOX_ORPHAN_REPAIR_APPROVED=<label>`) | `hotfix/release-r-orphan-payment` `d9945518` · regression test fails without fix |

## Frontend rules for the uncommitted work

The author commits it to their own branch. When it lands: revert the sessionStorage token store (memory + httpOnly
refresh cookie per ARCHITECTURE.md) and replace the `/api/v1`-stripping interceptor with a correct base URL.

## Branch clean-up (pending owner OK)

Remote branches merged into `main`, to delete after the owner confirms: `phase/*`, `feat/master-phases-1-2`, `integration/master-phases`,
`chore/owner-followups`, `feat/master-prompt-phase1`, `fix/main-gate-failures` (after merge). Frontend `feat/factory-plates-single-door` pushed as a backup branch (no merge).

## Temporary worktrees (owner deletes)

Backend: `…/scratchpad/gate4` (detached `04fd004c`). Frontend: `…/scratchpad/fe-plates` (`feat/factory-plates-single-door`).
`…` = `/tmp/claude-1000/-home-hassaanqazi-Documents-Qbox-WorkSpace/c9283964-79bc-4f18-8d8b-b350a1983672`. Earlier worktrees were lost in a reboot and pruned.

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
6. **Legacy routes** (`Qbox-Backend/docs/shipments/LEGACY_ROUTE_USAGE_2026-10.md`): zero calls for legacy payments checkout/detail/webhook, wallets, ledger, refunds, invoices, payment-methods, pricing, commissions, revenue; promotions, subscriptions and merchant payouts are in use. Retiring needs owner approval and a check of the webhook URLs set in the Moyasar dashboard.
7. Accountant: names / reporting lines of new ledger accounts 1300 disputed funds, 5400 chargeback losses, 2150 customer credit holds.
8. Hardware: confirm door sensor / lock feedback / evidence camera per model (capability flags default to false); plate number format.

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
- 2026-10-05 Owner: branch per phase → `integration/master-phases`; main reset to `origin/main`; hotfix branches from `598712bd`.
- 2026-10-05 Owner: ledger reversals for hotfixes a/c = journal credit holds + repair command.
- 2026-10-05 Owner: shared compartment mode kept; drf-yasg frozen (ADR 0006, no new usage, test enforces).
- 2026-10-05 Owner: no local Docker; every gate runs on the VPS (see "How gates run").
- 2026-10-05 Single-door Qbox always allocates its door; `QBOX_COMPARTMENT_SHARING=strict` only affects multi-compartment models (ADR 0004 amended).
- 2026-10-05 Printed-QR check takes the scanned text; photos are decoded in the browser (`BarcodeDetector`), no image library added to the backend.
- 2026-10-05 Owner: backend work directly on `main` under the "Rules for backend main" (replaces branch-per-phase); frontend stays on branches.
- 2026-10-05 Owner: provisional v2 batched-events endpoint accepted as is.
- 2026-10-05 `QBOX_DEGRADED_OWNER_CONFIRMATION` (default on): owner prompt for DEGRADED deliveries, switchable without a deploy.
- 2026-10-05 Owner: the owner runs every push to `main`; I prepare gated batches and run the post-deploy checks.
- 2026-10-05 No tests on the VPS ever again (Hostinger CPU cap + outage). Crash-looping host services disabled; RabbitMQ health check lightened; deploys build before stopping the stack and run one at a time.
- 2026-10-07 Status report written: `docs/reports/STATUS_2026-10-07.md`.
