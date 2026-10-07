# QBox master prompt — progress

Process (from 2026-10-07): **`QBOX_FINAL_COMPLETION_PROMPT.md`** — it replaces the process rules of all earlier
prompts; the master, phases 3–13 and R2 prompts remain feature descriptions only.
Repos: `Qbox-Backend` on `main`. `Qbox-Frontend-Panels` — `main` carries another author's uncommitted work, so frontend
work stays on branches until the owner says otherwise.

## How we work (2026-10-07)

1. One branch, `main`; logical local commits. No gate/integration/phase branches (deleted 2026-10-07).
   **No pre-push hooks** (removed 2026-10-07 from backend, workspace and frontend repos).
2. The owner pushes `main`; `.github/workflows/deploy.yml` **only builds and deploys — no tests in CI** (owner
   decision 2026-10-07). `deploy.sh`: backup before migrations, health gate, automatic rollback,
   `/var/log/qbox-deploy.log`. Details: `Qbox-Backend/docs/runbooks/DEPLOY.md`.
3. Before handing over a push: full suite locally (throwaway PostgreSQL) → "ready to push <sha>": contents, migrations,
   backup file if migrations. One push per finished item of the final prompt §4.
4. **Never run tests on the VPS.** Never print secret values: check secrets only with a length-only script.
5. A bad deploy rolls back by itself; fix forward or `git revert` + push. Never force-push `main`.

Latest full status: `docs/reports/STATUS_2026-10-07.md`; VPS: `docs/runbooks/VPS_LAYOUT.md`.

## Push log (newest last)

| Commit | What | Run link | Result |
|---|---|---|---|
| `c384f7c3` | current `main` (closes the Phase 5 gap) | not runnable as an exact commit: its workflow had no manual trigger and the push filter skips commits already on `main`; covered by the `073a456c` and `27d6e005` runs (descendants) | — |
| `99bb9edf` | stabilization batch: rotation support, safety check, AfterShip mapping fix | in the `27d6e005` batch | local full suite 1259 OK |
| `474ea56a` | QR key fallbacks | in the `27d6e005` batch | local full suite 1261 OK |
| `073a456c` | private business documents, `MEDIA_ROOT`→`uploads/`, `/warehouses/lookup/` fix | https://github.com/Hegmon-2/Qbox-Back-End/actions/runs/37576904676 | **green** (local 1270 OK) |
| `27d6e005` | private files + rotation + QR fallbacks + Tests manual trigger. Migrations `shipping 0009`, `accounts 0013` | https://github.com/Hegmon-2/Qbox-Back-End/actions/runs/37576976972 | **green; pushed by the owner 06:26 UTC, deployed (run 37581474919), rule 4 checks OK** |
| `c604eb49` | upload link for merchant documents (migration `accounts 0014`) + storage inventory doc | https://github.com/Hegmon-2/Qbox-Back-End/actions/runs/37579437556 | green (local 1283 OK) |
| `2914d96c` | old EMQX keys untracked; `.env.example` R2 names only (batch head incl. `c604eb49`; migration `accounts 0014`) | https://github.com/Hegmon-2/Qbox-Back-End/actions/runs/37580811221 | green; owner opened PR #13 07:10 UTC; backup `qbox-db-20261007-0711-27d6e005.dump` (17.7 MB) |
| `76b5a993` | item 4.1: PRs #13–#15 (`2914d96c` upload link + EMQX keys untracked, `96b1fceb` refund fix, `43c8544f` static outside repo), merged and deployed by the owner 07:14 UTC | deploy run on push | **deployed, checks OK** (0 errors / 20 min, `accounts 0014` applied, anonymous upload 403, `git status` empty); nginx `/static/` switched to `/var/www/qbox-static` 07:31 UTC |
| `90f4221f` | section 1: one pipeline, new `deploy.sh` (backup before migrations, health gate, rollback), DEPLOY.md. No migrations | pushed by the owner | local full suite 1285 OK |
| `b6e35ae3` + `03343b40` | pipeline without tests (owner decision) + deploy.sh SIGPIPE fix | owner push | **deployed 08:07 UTC, `result=ok`** |
| `76d20cb0` | security: no wildcard CORS default + WHEP Location (`bcd69672`), `CORS_ORIGINS_EXACT` (`41680a23`), merchant bank/contact data exposure (`76d20cb0`). No migrations | owner push | local full suite running |

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
- 2026-10-07 Stabilization round before Phase 7: daily backups (14 days) + restore test OK; cleanup done; DEBUG / rotation plans in `docs/runbooks/`.

## Frontend (Qbox-Frontend-Panels) — panels prompt (2026-10-07)

### §0 Repo preparation — done locally (not pushed)
- **`wip/uncommitted-2026-10`** (pushed, `967fc92`): the other author's 56 uncommitted files from frontend `main`
  (50 modified, 6 new), committed unchanged as a backup. Not merged. Contents: `/api/v1`-suffixed base URLs + an
  interceptor that strips `/api/v1` (not taken), a sessionStorage token store (not taken), customers/warehouses
  list and form fixes, Qbox settings page with device status / connectivity / cameras and a WHEP live view,
  AlertModal and dialog/drawer UI fixes, staff phone normalization, service-provider panel edits.
  Review per file (take / partial / drop): taken parts are listed in commit `33813ec` and `98b46ca`, `d344f53`.
- Local `main` = `origin/main` + merges of `fix/merchant-canonical-shipments` and `feat/factory-plates-single-door`
  (incl. `feat/factory-identity-stickers`) + typed API client (`f16d905`, OpenAPI snapshot + `pnpm check:api` in
  CI) + halala/Riyadh-time helpers (`870a3aa`) + the taken WIP parts. All `test.qbox.sa` → `backend.qbox.sa`.
  Checks: install, tokens, check:api, lint, typecheck, test, build — all pass.
- Open: factory panel has almost no AR/RTL yet (merchant and superadmin have i18n + RTL).

### §1 Service-provider removal
- VPS done: `/var/www/Qbox-Service-Provider` archived (`/root/backups/old-code/Qbox-Service-Provider-20261007.tar.gz`,
  copy on the development machine, checksum OK, deleted 2027-01-05 by cron) and deleted; nginx site removed
  (backup `/etc/nginx/backup/service-provider.qbox.sa.<stamp>.bak`), certificate deleted (`certbot delete`), other
  sites 200. **Owner: delete the DNS record `service-provider.qbox.sa` at Salla.**
- Backend check: `driver`, `service_provider`, `deliveries` are tombstones (apps.py + models for migrations only);
  no active code imports them; retired routes answer 410. Remaining mentions: retired-role lists
  (`accounts/retired.py`, login rejection), legacy export command, archived enum values in `wallets` /
  `commissions`. Proposal (not done): drop the three apps after squashing their migrations into a final
  "delete tables" migration once the legacy data export is confirmed archived.
- Frontend done (`bb5c440`): panel deleted (243 files), superadmin service-provider/driver screens, routes, columns, locale keys removed; shared roles cleaned; lockfile without its dependencies; all checks pass.

### §2 Frontend pipeline + go-live — done
- `deploy.yml` (push to main): checks + build, then merchant and superadmin released to
  `/var/www/qbox-panels/<app>/releases/<sha>/`, atomic `current` switch, health check, rollback, 5 releases
  (`fd26622`, `docs/runbooks/FRONTEND_DEPLOY.md`). Deploy user `qbox-deploy` (own SSH key in the repo secrets
  `VPS_DEPLOY_SSH_KEY`, pinned host key). `ci.yml` = pull requests only.
- **Live since 2026-10-07 09:34 UTC**: merchant.qbox.sa and super-admin.qbox.sa serve the new panels (initial
  release built locally from `bb5c440`; the pipeline replaces it on the first push). Checked: pages, deep links,
  assets 200, CSP/HSTS headers, superadmin `/api` proxy, wrong-login 401 through both panels.
- Old August builds archived (`/root/backups/old-code/*-20261007.tar.gz`, copies here, checksums OK) and removed.
- Backend CORS/CSRF env: exactly `https://merchant.qbox.sa`, `https://super-admin.qbox.sa` (+ backend for CSRF),
  `CORS_ORIGINS_EXACT=true`. Takes full effect when backend `41680a23` (and `bcd69672`: no ngrok default) are pushed.
- Factory panel: built and checked, not deployed. Proposal: `factory-panel.qbox.sa` (owner decides; DNS + certificate).
