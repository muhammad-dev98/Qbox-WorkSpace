# QBox Multi-Repository Workspace Instructions

## 1. Workspace Overview

This workspace contains multiple completely independent repositories belonging to the QBox platform.

Current repositories:

* `Qbox-Backend/` — QBox Backend/API repository
* `Qbox-Hardware/` — QBox hardware/device software repository

These repositories MUST remain architecturally and technically independent.

---

# 2. CRITICAL REPOSITORY BOUNDARY RULE

`Qbox-Back-End/` and `qbox-hardware/` are SEPARATE repositories.

DO NOT merge them into one codebase.

DO NOT treat the workspace root as a single application.

Each repository has:

* its own Git repository
* its own source code
* its own dependencies
* its own package/project configuration
* its own tests
* its own deployment process
* its own environment variables
* its own release lifecycle
* its own architecture

Never create cross-repository imports.

Never make one repository depend on the source code of the other repository.

---

# 3. NO DIRECT SOURCE-CODE SHARING

The backend and hardware repositories MUST NOT directly consume each other's source code.

Forbidden examples:

```python
from qbox_hardware.some_module import ...
```

inside the backend.

Also forbidden:

```python
from backend.some_module import ...
```

inside the hardware repository.

Do not:

* import Python modules from the other repository
* import TypeScript/JavaScript modules from the other repository
* copy source files from one repository into the other
* copy classes, services, models, repositories, utilities, or business logic between repositories
* add the other repository as a local package dependency
* modify PYTHONPATH/PATH/node_modules/package paths to access the other repository
* create symlinks to source-code directories across repositories
* reference files from the other repository at runtime
* vendor the other repository's source code
* duplicate implementation merely to bypass the repository boundary

The repositories communicate through contracts, not source-code dependencies.

---

# 4. ALLOWED CROSS-REPOSITORY COMMUNICATION

The repositories may communicate ONLY through explicit external contracts.

Examples:

### Backend → Hardware

* MQTT commands
* MQTT configuration messages
* OTA instructions
* device provisioning instructions
* device lifecycle commands
* HTTP APIs where explicitly designed
* documented authentication/provisioning protocols

### Hardware → Backend

* MQTT telemetry
* MQTT device events
* device status messages
* health reports
* heartbeat messages
* QR/device events
* HTTP API calls where explicitly designed
* documented registration/provisioning protocols

The hardware device should behave like an independent client of the backend platform.

The backend should treat hardware as an external system/device.

---

# 5. CONTRACTS ARE THE BRIDGE

If both repositories need to agree on something, define the contract rather than sharing implementation code.

Examples:

```text
contracts/
├── mqtt/
│   ├── device-registration.md
│   ├── telemetry.md
│   ├── commands.md
│   ├── device-status.md
│   └── events.md
│
├── api/
│   ├── device-registration.md
│   ├── provisioning.md
│   └── device-commands.md
│
└── schemas/
    ├── telemetry/
    ├── device-events/
    └── commands/
```

Contracts may contain:

* topic names
* endpoint definitions
* request payloads
* response payloads
* JSON schemas
* field definitions
* enums
* status values
* authentication requirements
* error formats
* versioning rules
* compatibility rules

Contracts MUST NOT contain application implementation from either repository.

---

# 6. WHEN A CHANGE REQUIRES BOTH REPOSITORIES

Sometimes a feature will require changes to both repositories.

For example:

```text
Feature: Device OTA Update

Backend:
- create OTA rollout
- publish MQTT command
- track rollout state
- receive device status

Hardware:
- receive MQTT command
- validate firmware
- download firmware
- verify firmware
- install firmware
- report result
```

This is allowed.

However, implement each side independently inside its own repository.

Do NOT solve the problem by moving implementation from one repository into the other.

The correct approach is:

```text
Backend
   |
   | MQTT contract
   v
Hardware
```

not:

```text
Backend source code
        |
        v
Hardware source code
```

---

# 7. CODEX WORKING RULE

When working from the workspace root:

1. Determine which repository owns the requested change.
2. Read that repository's `AGENTS.md`.
3. Treat that repository as the authoritative source for its implementation.
4. Do not modify the other repository unless the task explicitly requires a coordinated cross-repository change.
5. If both repositories must change, keep every implementation inside its owning repository.
6. Use contracts/interfaces to coordinate the repositories.
7. Never create direct source-code dependencies between repositories.

---

# 8. REPOSITORY OWNERSHIP

## Backend

`Qbox-Back-End/` owns:

* REST APIs
* authentication
* authorization
* RBAC
* users/accounts
* homeowners
* merchants
* service providers
* drivers
* shipments
* payments
* subscriptions
* device records
* device lifecycle records
* backend-side provisioning
* backend-side telemetry processing
* backend-side OTA orchestration
* backend business rules
* databases
* admin functionality
* notifications
* analytics

The backend owns the server-side representation and orchestration of QBox devices.

---

## Hardware

`qbox-hardware/` owns:

* Raspberry Pi/device runtime
* hardware abstraction
* GPIO
* relay control
* solenoid control
* buzzer
* LEDs
* cameras
* QR scanning
* local device agents
* MQTT client implementation
* local configuration
* device identity
* certificates/credentials used by the device
* telemetry collection
* health monitoring
* local storage
* device watchdog
* OTA execution
* hardware safety behavior
* offline behavior
* boot/startup behavior
* device-level recovery

The hardware repository owns device-side execution.

---

# 9. DATABASE BOUNDARY

The hardware repository MUST NOT access the backend database directly.

Forbidden:

```text
Hardware → PostgreSQL
Hardware → Django ORM
Hardware → Backend database tables
Hardware → Backend database models
```

Correct:

```text
Hardware
   ↓
MQTT / HTTP
   ↓
Backend
   ↓
Database
```

The backend owns its database.

The hardware owns only its local device state/storage.

---

# 10. API BOUNDARY

The hardware repository may call backend APIs only through documented API contracts.

Do not import:

* Django serializers
* Django models
* Django services
* Django repositories
* Django permissions
* Django utilities
* backend Python packages

into the hardware repository.

Likewise, the backend must not import hardware implementation modules.

---

# 11. MQTT BOUNDARY

MQTT is an integration protocol, not a source-code sharing mechanism.

If a backend MQTT topic and hardware MQTT topic must match, document the topic contract.

For example:

```text
qbox/{device_id}/commands
qbox/{device_id}/telemetry
qbox/{device_id}/events
qbox/{device_id}/status
```

Both repositories independently implement the MQTT contract.

Do not share MQTT implementation code between repositories.

---

# 12. VERSIONING

Cross-repository contracts MUST be versioned.

For example:

```text
MQTT protocol v1
API contract v1
Telemetry schema v1
Device command schema v1
```

When changing a contract:

1. Document the change.
2. Consider backward compatibility.
3. Update the owning repository implementation.
4. Update the other repository only when necessary.
5. Avoid breaking deployed devices.

Never silently change a cross-repository contract.

---

# 13. GIT RULES

Each repository has its own Git history.

Do not:

* initialize another Git repository inside an existing repository
* remove `.git` directories
* merge Git histories
* move source files between repositories merely to simplify development
* commit files belonging to the other repository

Expected structure:

```text
QBox-Workspace/
├── Qbox-Back-End/.git/
└── qbox-hardware/.git/
```

Both repositories must remain independently cloneable.

---

# 14. CROSS-REPOSITORY TASKS

If a task says:

> "Implement device registration end-to-end"

do NOT put everything in one repository.

Instead identify ownership:

```text
Backend:
- registration API
- provisioning records
- device identity records
- credentials
- lifecycle state

Hardware:
- device identity generation/loading
- registration client
- provisioning agent
- credential storage
- registration state

Contract:
- registration request/response
- authentication
- MQTT topics
- status values
```

Each repository implements only its own responsibilities.

---

# 15. IF INFORMATION IS MISSING

If implementation in one repository requires knowledge about the other repository:

DO NOT import its code.

Instead inspect:

1. the repository's documentation
2. the workspace `contracts/`
3. API specifications
4. MQTT specifications
5. architecture documentation
6. README files
7. configuration examples
8. schemas

If the contract does not exist, create/update the contract documentation first.

---

# 16. CHANGE DISCIPLINE

Before modifying files, determine:

```text
Repository:
Ownership:
Reason:
Cross-repository contract involved:
Expected interface:
```

Avoid unnecessary changes outside the repository that owns the functionality.

---

# 17. ABSOLUTE RULE

The following architecture MUST always remain true:

```text
                 QBox Workspace
                       |
          +------------+------------+
          |                         |
          v                         v
   Qbox-Back-End              qbox-hardware
          |                         |
          |                         |
       Backend                  Device Runtime
       Logic                    Hardware Logic
          |                         |
          v                         v
      Database              Physical Hardware
          \                         /
           \                       /
            +---- Contracts -------+
                  |
             MQTT / HTTP
```

The repositories are peers, not parent/child codebases.

The backend does not own hardware source code.

The hardware does not own backend source code.

They integrate through stable, explicit, versioned contracts.

This rule takes precedence over convenience.

If a proposed implementation violates this boundary, stop and redesign it using an explicit API, MQTT contract, schema, or other external interface.
