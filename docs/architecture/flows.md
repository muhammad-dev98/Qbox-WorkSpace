# QBox Platform — System Flow Diagrams

This document contains the production-grade Mermaid.js flow diagrams for the QBox Smart
Locker Platform. It covers the end-to-end system workflow across all five roles, the
technician installation execution sequence, and the three core state machines that govern
the platform: **User Account Lifecycle**, **Hardware Unit Lifecycle**, and
**Installation Job Lifecycle**.

## How to preview / render these diagrams

**Option A — VS Code (recommended for editing)**
1. Install the extension `bierner.markdown-mermaid` (or `Markdown Preview Mermaid Support`).
2. Open this file and run `Markdown: Open Preview` (`Ctrl+Shift+V` / `Cmd+Shift+V`).
3. Diagrams render inline as you edit.

**Option B — Compile to SVG/PNG via `@mermaid-js/mermaid-cli`**
```bash
npm install -g @mermaid-js/mermaid-cli

# Extract a single diagram block to its own .mmd file, then:
mmdc -i flow.mmd -o flow.svg -t neutral -b transparent

# Batch example: render every fenced mermaid block in this file (requires a small
# splitter script, or paste each block manually into its own .mmd file).
mmdc -i flows.md -o flows.svg -t neutral
```

**Option C — GitHub / GitLab**
Both render ```mermaid fenced blocks natively in the web UI — no setup required when
viewing this file in a pull request.

---

## 1. End-to-End System Workflow (All 5 Roles)

```mermaid
flowchart TD
    subgraph ONBOARD["Onboarding & Access Control"]
        direction TB
        A1([Homeowner / Merchant<br/>visits registration portal]) --> A2["Submit UserRegistrationDTO<br/>+ SPLAddressDTO"]
        A2 --> A3{SPL Address<br/>validation passes?}
        A3 -- "No — malformed Short Address,<br/>missing GPS coords" --> A4["Return 422<br/>ValidationError"]
        A4 --> A2
        A3 -- Yes --> A5["Create User<br/>status = PENDING_APPROVAL"]
        A5 --> A6[/Superadmin Review Queue/]
    end

    subgraph SUPERADMIN["Superadmin — Account Governance"]
        direction TB
        A6 --> S1{Superadmin decision}
        S1 -- Reject --> S2["status = REJECTED<br/>reason recorded"]
        S2 --> S3["Notify user via email/SMS"]
        S1 -- Approve --> S4["status = APPROVED<br/>OAuth2 client enabled"]
        S4 --> S5["Notify user: account active"]
    end

    S3 --> END1([End — user may re-apply])
    S5 --> B1

    subgraph REQUEST["Installation Request"]
        direction TB
        B1([Approved user logs in<br/>via JWT/OAuth2]) --> B2["Select verified SPL Address"]
        B2 --> B3["Create Installation Request<br/>status = QUEUED"]
        B3 --> B4[/Factory Admin Dashboard/]
    end

    subgraph FACTORY["Factory Admin / Inventory Manager"]
        direction TB
        B4 --> F1["View QUEUED requests"]
        F1 --> F2{Hardware unit<br/>READY_FOR_INSTALL<br/>available?}
        F2 -- No --> F3["Escalate to procurement /<br/>hold in QUEUED"]
        F3 --> F1
        F2 -- Yes --> F4["Reserve hardware unit<br/>(atomic lock, Serial/MAC bound)<br/>status = ASSIGNED"]
        F4 --> F5["Assign available Technician"]
        F5 --> F6["Set installation<br/>schedule window"]
        F6 --> F7["Order status = SCHEDULED<br/>Job status = CREATED → SCHEDULED"]
        F7 --> F8["Notify Technician (push/SMS)<br/>Notify Customer (confirmation)"]
    end

    F8 --> T1

    subgraph TECH["Field Technician — Mobile App"]
        direction TB
        T1([Technician accepts job]) --> T2["Job status = IN_TRANSIT"]
        T2 --> T3["Arrive on-site<br/>GPS geofence check vs SPL coords"]
        T3 --> T4{Geofence<br/>match?}
        T4 -- No --> T5["Flag anomaly,<br/>allow manual override + reason"]
        T5 --> T6
        T4 -- Yes --> T6["Scan hardware QR/barcode<br/>Serial + MAC validated vs assignment"]
        T6 --> T7{Matches<br/>assigned unit?}
        T7 -- No --> T8["Block install —<br/>report wrong-unit exception"]
        T8 --> T8R(["⟲ Routed back to Factory Admin<br/>queue for reassignment"])
        T7 -- Yes --> T9["BLE/Wi-Fi provisioning +<br/>MQTT broker handshake"]
        T9 --> T10{Handshake<br/>succeeded?}
        T10 -- "Timeout / failure" --> T11["Retry (max N) →<br/>else FAILED_PROVISIONING"]
        T11 --> T9
        T10 -- Yes --> T12["Run automated diagnostics<br/>(see sequence diagram)"]
        T12 --> T13{Diagnostics<br/>PASS?}
        T13 -- Fail --> T14["Log diagnostic fail report"]
        T14 --> T15{Retry?}
        T15 -- Yes --> T12
        T15 -- No --> T16["Job = FAILED_DIAGNOSTIC<br/>Hardware = DEFECTIVE<br/>returned to inventory"]
        T16 --> T16R(["⟲ Routed back to Factory Admin<br/>queue — hardware swap needed"])
        T13 -- Pass --> T17["Capture proof-of-install photo"]
        T17 --> T18["Capture customer<br/>digital signature"]
        T18 --> T19["Job status = COMPLETED"]
    end

    subgraph ACTIVATE["Platform Activation"]
        direction TB
        T19 --> C1["Hardware status = ACTIVE"]
        C1 --> C2["Link QBox unit to<br/>Homeowner/Merchant account"]
        C2 --> C3["Provision Locker Subscription"]
        C3 --> C4[/Customer notified —<br/>QBox ready to use/]
    end

    C4 --> END2([End])

    style ONBOARD fill:#eef2ff,stroke:#4f46e5
    style SUPERADMIN fill:#fef3c7,stroke:#b45309
    style REQUEST fill:#ecfeff,stroke:#0891b2
    style FACTORY fill:#f0fdf4,stroke:#15803d
    style TECH fill:#fdf2f8,stroke:#be185d
    style ACTIVATE fill:#f5f3ff,stroke:#6d28d9
```

---

## 2. Technician Installation Execution — Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Tech as Field Technician<br/>(Mobile App)
    participant BE as Backend API<br/>(Installation Service)
    participant Edge as QBox Edge Device<br/>(BLE/Wi-Fi)
    participant MQTT as MQTT Broker /<br/>Edge Backend
    participant Diag as Diagnostics Engine

    Tech->>BE: POST /jobs/{id}/accept
    BE-->>Tech: 200 OK { status: IN_TRANSIT }

    Note over Tech: Technician travels to site

    Tech->>BE: POST /jobs/{id}/checkin { lat, lng }
    BE->>BE: Validate GPS within SPL geofence radius
    alt Geofence mismatch
        BE-->>Tech: 409 { error: GEOFENCE_MISMATCH }
        Tech->>BE: POST /jobs/{id}/override { reason }
        BE-->>Tech: 200 OK (override logged, audit trail)
    else Geofence OK
        BE-->>Tech: 200 OK { status: ARRIVED }
    end

    Tech->>Tech: Scan hardware QR/barcode
    Tech->>BE: POST /jobs/{id}/verify-hardware { serial, mac }
    BE->>BE: Match against HardwareAssignmentDTO
    alt Serial/MAC mismatch
        BE-->>Tech: 422 { error: UNIT_MISMATCH }
        Note over Tech,BE: Job blocked — technician must request correct unit
    else Match confirmed
        BE-->>Tech: 200 OK { status: HARDWARE_VERIFIED }
    end

    Tech->>Edge: Initiate BLE pairing
    Edge-->>Tech: BLE advertisement + pairing token
    Tech->>Edge: Push Wi-Fi credentials over BLE
    Edge->>MQTT: Connect + authenticate (device cert / token)
    alt Handshake timeout (network / credential failure)
        MQTT-->>Edge: Connection refused / timeout
        Edge-->>Tech: Provisioning failed
        Tech->>BE: POST /jobs/{id}/provisioning-retry
        Note over Tech,Edge: Retry loop, bounded (e.g. 3 attempts)
    else Handshake succeeds
        MQTT-->>Edge: CONNACK + device registered
        Edge-->>Tech: Provisioning success
        Tech->>BE: POST /jobs/{id}/provisioning-complete
        BE-->>Tech: 200 OK { status: PROVISIONED }
    end

    BE->>Diag: Trigger diagnostics run { device_id }
    Diag->>Edge: Command: cycle solenoid lock (open/close)
    Edge-->>Diag: Lock cycle result + latency
    Diag->>Edge: Command: read door position sensor
    Edge-->>Diag: Sensor state (OPEN/CLOSED)
    Diag->>Edge: Command: pulse status LEDs
    Edge-->>Diag: LED self-test result
    Diag->>Edge: Command: trigger acoustic buzzer
    Edge-->>Diag: Buzzer ACK + audio level
    Diag->>Edge: Request dual-camera stream check
    Edge-->>Diag: Stream A/B health (resolution, fps, signal)

    Diag->>Diag: Aggregate TechnicianDiagnosticPayloadDTO
    alt Any check fails or times out
        Diag-->>BE: Diagnostics = FAIL { failed_checks[] }
        BE-->>Tech: 200 { status: DIAGNOSTICS_FAILED, report }
        Tech->>BE: POST /jobs/{id}/diagnostics-retry (optional)
        Note over Tech,Diag: Bounded retry, else FAILED_DIAGNOSTIC
    else All checks pass
        Diag-->>BE: Diagnostics = PASS { metrics }
        BE-->>Tech: 200 { status: DIAGNOSTICS_PASSED }

        Tech->>Tech: Capture proof-of-installation photo
        Tech->>BE: POST /jobs/{id}/photo (multipart)
        BE-->>Tech: 200 OK { photo_url }

        Tech->>Tech: Capture customer digital signature
        Tech->>BE: POST /jobs/{id}/signature (image/base64)
        BE-->>Tech: 200 OK { signature_url }

        Tech->>BE: POST /jobs/{id}/complete
        BE->>BE: Transaction: job=COMPLETED,<br/>hardware=ACTIVE,<br/>link hardware→customer account,<br/>create Locker Subscription
        BE-->>Tech: 200 OK { status: COMPLETED }
        BE-->>MQTT: Publish device activation event
    end
```

---

## 3. User Account Lifecycle — State Diagram

```mermaid
stateDiagram-v2
    [*] --> DRAFT: Registration form started

    DRAFT --> PENDING_APPROVAL: Submit valid payload<br/>(UserRegistrationDTO + SPLAddressDTO)
    DRAFT --> DRAFT: Validation failure (retry submission)

    PENDING_APPROVAL --> APPROVED: Superadmin approves
    PENDING_APPROVAL --> REJECTED: Superadmin rejects<br/>(reason required)

    REJECTED --> PENDING_APPROVAL: User resubmits<br/>with corrections

    APPROVED --> SUSPENDED: Superadmin suspends<br/>(policy violation, fraud flag,<br/>payment default)
    SUSPENDED --> APPROVED: Superadmin reinstates

    APPROVED --> DEACTIVATED: User closes account /<br/>Superadmin deactivates
    SUSPENDED --> DEACTIVATED: Superadmin deactivates<br/>permanently

    DEACTIVATED --> [*]

    note right of PENDING_APPROVAL
        JWT/OAuth2 login is DISABLED
        until status = APPROVED.
        No installation requests
        may be created.
    end note

    note right of SUSPENDED
        Existing JWT sessions are
        revoked immediately.
        Active lockers remain
        physically operable but
        API access is blocked.
    end note
```

---

## 4. Hardware Unit Lifecycle — State Diagram

```mermaid
stateDiagram-v2
    [*] --> IN_INVENTORY: Unit received from<br/>manufacturing / warehouse intake

    IN_INVENTORY --> STAGED: Factory Admin marks<br/>READY_FOR_INSTALL<br/>(passed incoming QC)
    IN_INVENTORY --> QUARANTINED: Incoming QC fails

    QUARANTINED --> IN_INVENTORY: Re-tested, passes QC
    QUARANTINED --> DECOMMISSIONED: Unrepairable

    STAGED --> ASSIGNED: Factory Admin reserves unit<br/>for Installation Job<br/>(atomic inventory lock)
    ASSIGNED --> STAGED: Job cancelled before<br/>technician dispatch<br/>(lock released)

    ASSIGNED --> PROVISIONING: Technician begins<br/>BLE/Wi-Fi + MQTT handshake

    PROVISIONING --> PROVISIONING: Handshake retry (bounded attempts)
    PROVISIONING --> ASSIGNED: Provisioning abandoned /<br/>job rescheduled

    PROVISIONING --> DIAGNOSTICS: Cloud handshake confirmed

    DIAGNOSTICS --> ACTIVE: All diagnostic checks PASS<br/>+ proof photo + signature captured
    DIAGNOSTICS --> DEFECTIVE: Diagnostics FAIL<br/>(no more retries)<br/>returned to inventory pipeline

    DEFECTIVE --> IN_INVENTORY: RMA / repair cycle<br/>completed, re-QC passed
    DEFECTIVE --> DECOMMISSIONED: Repair not viable

    ACTIVE --> MAINTENANCE: Fault reported<br/>(remote diagnostic alert or<br/>customer ticket)
    MAINTENANCE --> ACTIVE: Repair verified on-site,<br/>diagnostics re-run and PASS
    MAINTENANCE --> DECOMMISSIONED: End-of-life during<br/>maintenance visit

    ACTIVE --> DECOMMISSIONED: End-of-life /<br/>customer churn + unit retrieved

    DECOMMISSIONED --> [*]

    note right of ASSIGNED
        Reservation MUST be an atomic
        DB transaction (SELECT ... FOR UPDATE
        or optimistic lock) to prevent two
        Factory Admins double-booking
        the same Serial/MAC.
    end note
```

---

## 5. Installation Job Lifecycle — State Diagram

```mermaid
stateDiagram-v2
    [*] --> CREATED: Homeowner/Merchant<br/>installation request accepted<br/>into Factory Admin queue

    CREATED --> SCHEDULED: Factory Admin assigns<br/>hardware + technician + time window

    SCHEDULED --> CANCELLED: Customer or Admin<br/>cancels before dispatch
    SCHEDULED --> IN_TRANSIT: Technician accepts job

    IN_TRANSIT --> IN_TRANSIT: En route (location pings)
    IN_TRANSIT --> IN_PROGRESS: Arrival confirmed<br/>(geofence check / override)

    IN_PROGRESS --> IN_PROGRESS: Retry
    IN_PROGRESS --> FAILED_PROVISIONING: Provisioning handshake<br/>exhausts retries

    note right of IN_PROGRESS
        Self-loop covers the bounded
        hardware-scan / BLE-Wi-Fi
        provisioning retry cycle before
        either success or FAILED_PROVISIONING.
    end note

    IN_PROGRESS --> DIAGNOSTICS_RUNNING: Cloud handshake confirmed,<br/>automated diagnostics triggered

    DIAGNOSTICS_RUNNING --> COMPLETED: All checks PASS +<br/>photo + signature captured
    DIAGNOSTICS_RUNNING --> FAILED_DIAGNOSTIC: One or more checks FAIL<br/>after bounded retries

    FAILED_PROVISIONING --> RESCHEDULED: Retries exhausted —<br/>new visit scheduled

    FAILED_DIAGNOSTIC --> RESCHEDULED: Hardware swapped,<br/>new visit scheduled
    FAILED_DIAGNOSTIC --> [*]: Hardware marked DEFECTIVE,<br/>job closed as failed

    RESCHEDULED --> SCHEDULED: New technician/time window<br/>assigned (may reuse or<br/>replace hardware unit)

    COMPLETED --> [*]
    CANCELLED --> [*]

    note right of DIAGNOSTICS_RUNNING
        Diagnostics timeout (no response
        from Edge device within SLA,
        e.g. 60s) is treated as a FAIL
        and logged as a distinct
        TIMEOUT diagnostic_code.
    end note
```

---

## 6. Edge-Case Reference

| Scenario | Where handled | Behavior |
|---|---|---|
| SPL address regex validation failure | Onboarding flow (§1), Contracts doc | 422 response, user must correct fields before `PENDING_APPROVAL` is created |
| GPS geofence mismatch at install site | Sequence diagram (§2), Job Lifecycle (§5) | Blocks default path; technician may log a manual override with a mandatory reason, fully audited |
| Wrong hardware unit scanned | Sequence diagram (§2) | Hard block — job cannot proceed; routed back to Factory Admin for reassignment |
| BLE/Wi-Fi provisioning timeout | Sequence diagram (§2), Hardware Lifecycle (§4) | Bounded retry (recommend 3 attempts with backoff); exhausted retries → `FAILED_PROVISIONING` |
| MQTT broker handshake rejected (bad cert/token) | Sequence diagram (§2) | Same retry policy as above; persistent failure escalates to Factory Admin / DevOps alert |
| Diagnostic check timeout (no Edge response) | Sequence diagram (§2), Job Lifecycle (§5) | Treated as FAIL with `diagnostic_code = TIMEOUT`; counts toward retry budget |
| Diagnostics fail after max retries | Job Lifecycle (§5), Hardware Lifecycle (§4) | `FAILED_DIAGNOSTIC`; hardware → `DEFECTIVE`; job → reschedule or terminal failure |
| Double-booking a hardware unit | Hardware Lifecycle (§4), Database doc | Prevented via atomic row-lock/optimistic-concurrency reservation at `ASSIGNED` transition |
| Superadmin rejects account | Account Lifecycle (§3) | User can resubmit with corrected data; no login/API access until `APPROVED` |
| Account suspended while hardware is `ACTIVE` | Account Lifecycle (§3) | API/app access revoked; physical locker keeps functioning offline-safe until reinstated or unit is decommissioned |
