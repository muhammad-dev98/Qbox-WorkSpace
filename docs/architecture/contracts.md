# QBox Platform — Core Data Contracts

Defines the strict data contracts exchanged between clients (Homeowner/Merchant portals,
Factory Admin dashboard, Technician mobile app) and the backend. Each contract is provided
as a **Pydantic v2 DTO** (source of truth, used for runtime validation) plus an equivalent
**TypeScript interface** (for frontend/mobile clients) and a **JSON Schema** where the shape
benefits from being framework-agnostic (SPL address).

All timestamps are ISO-8601 UTC. All identifiers are UUIDv4 unless noted.

---

## 1. `SPLAddressDTO` — Saudi Post National Address

Saudi Post (SPL) National Addresses follow a fixed structure. The **Short Address** is the
canonical 8-character token: 4 letters (building code) + 4 digits (zone code), e.g.
`RRRD1234`. All other fields are captured for physical dispatch and geofencing.

### Validation rules

| Field | Rule |
|---|---|
| `short_address` | Regex `^[A-Z]{4}[0-9]{4}$` — always uppercase, exactly 4 letters then 4 digits |
| `building_number` | Regex `^[0-9]{4}$` — 4-digit building number per SPL spec |
| `street_name` | Non-empty, 2–100 chars, Unicode (supports Arabic + Latin script) |
| `district` | Non-empty, 2–100 chars |
| `city` | Non-empty, 2–100 chars; recommend enum/lookup table against SPL's official city list |
| `postal_code` | Regex `^[0-9]{5}$` — 5-digit postal code |
| `additional_code` | Regex `^[0-9]{4}$` — 4-digit unit disambiguator |
| `latitude` | Float, range `16.0` to `33.0` (Saudi Arabia bounding box), 6 decimal precision |
| `longitude` | Float, range `34.0` to `56.0` (Saudi Arabia bounding box), 6 decimal precision |

> The combination `short_address + building_number + additional_code` is the unique SPL
> key and should be indexed as such (see [database.md](./database.md)).

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SPLAddressDTO",
  "type": "object",
  "required": [
    "short_address", "building_number", "street_name", "district",
    "city", "postal_code", "additional_code", "latitude", "longitude"
  ],
  "properties": {
    "short_address":   { "type": "string", "pattern": "^[A-Z]{4}[0-9]{4}$", "examples": ["RRRD1234"] },
    "building_number": { "type": "string", "pattern": "^[0-9]{4}$" },
    "street_name":     { "type": "string", "minLength": 2, "maxLength": 100 },
    "district":        { "type": "string", "minLength": 2, "maxLength": 100 },
    "city":            { "type": "string", "minLength": 2, "maxLength": 100 },
    "postal_code":     { "type": "string", "pattern": "^[0-9]{5}$" },
    "additional_code": { "type": "string", "pattern": "^[0-9]{4}$" },
    "latitude":        { "type": "number", "minimum": 16.0, "maximum": 33.0 },
    "longitude":       { "type": "number", "minimum": 34.0, "maximum": 56.0 },
    "unit_number":     { "type": ["string", "null"], "maxLength": 20 }
  },
  "additionalProperties": false
}
```

### Pydantic DTO

```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re

SHORT_ADDRESS_RE = re.compile(r"^[A-Z]{4}[0-9]{4}$")
BUILDING_NUMBER_RE = re.compile(r"^[0-9]{4}$")
POSTAL_CODE_RE = re.compile(r"^[0-9]{5}$")
ADDITIONAL_CODE_RE = re.compile(r"^[0-9]{4}$")


class SPLAddressDTO(BaseModel):
    short_address: str = Field(..., description="e.g. RRRD1234")
    building_number: str
    street_name: str = Field(..., min_length=2, max_length=100)
    district: str = Field(..., min_length=2, max_length=100)
    city: str = Field(..., min_length=2, max_length=100)
    postal_code: str
    additional_code: str
    latitude: float = Field(..., ge=16.0, le=33.0)
    longitude: float = Field(..., ge=34.0, le=56.0)
    unit_number: Optional[str] = Field(default=None, max_length=20)

    @field_validator("short_address")
    @classmethod
    def validate_short_address(cls, v: str) -> str:
        v = v.strip().upper()
        if not SHORT_ADDRESS_RE.match(v):
            raise ValueError("short_address must match 4 letters + 4 digits, e.g. RRRD1234")
        return v

    @field_validator("building_number")
    @classmethod
    def validate_building_number(cls, v: str) -> str:
        if not BUILDING_NUMBER_RE.match(v):
            raise ValueError("building_number must be exactly 4 digits")
        return v

    @field_validator("postal_code")
    @classmethod
    def validate_postal_code(cls, v: str) -> str:
        if not POSTAL_CODE_RE.match(v):
            raise ValueError("postal_code must be exactly 5 digits")
        return v

    @field_validator("additional_code")
    @classmethod
    def validate_additional_code(cls, v: str) -> str:
        if not ADDITIONAL_CODE_RE.match(v):
            raise ValueError("additional_code must be exactly 4 digits")
        return v
```

### TypeScript interface

```typescript
export interface SPLAddressDTO {
  shortAddress: string;      // ^[A-Z]{4}[0-9]{4}$ e.g. "RRRD1234"
  buildingNumber: string;    // ^[0-9]{4}$
  streetName: string;
  district: string;
  city: string;
  postalCode: string;        // ^[0-9]{5}$
  additionalCode: string;    // ^[0-9]{4}$
  latitude: number;          // 16.0–33.0
  longitude: number;         // 34.0–56.0
  unitNumber?: string | null;
}

export const SHORT_ADDRESS_REGEX = /^[A-Z]{4}[0-9]{4}$/;
export const BUILDING_NUMBER_REGEX = /^[0-9]{4}$/;
export const POSTAL_CODE_REGEX = /^[0-9]{5}$/;
export const ADDITIONAL_CODE_REGEX = /^[0-9]{4}$/;
```

---

## 2. `UserRegistrationDTO` — Homeowner vs. Merchant

A shared base carries identity + SPL address; each account type extends it with
type-specific fields. Discriminated by `account_type`.

### Pydantic DTO

```python
from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Literal, Optional, Union
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

PHONE_RE = re.compile(r"^\+966[0-9]{9}$")            # Saudi E.164 format
CR_NUMBER_RE = re.compile(r"^[0-9]{10}$")             # Commercial Registration number
NATIONAL_ID_RE = re.compile(r"^[12][0-9]{9}$")        # Saudi national ID / Iqama


class AccountType(str, Enum):
    HOMEOWNER = "HOMEOWNER"
    MERCHANT = "MERCHANT"


class UserRegistrationBaseDTO(BaseModel):
    account_type: AccountType
    full_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    phone_number: str
    password: str = Field(..., min_length=10)
    spl_address: SPLAddressDTO
    accepted_terms_at: str  # ISO-8601 timestamp of ToS acceptance

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("phone_number must be Saudi E.164 format, e.g. +9665XXXXXXXX")
        return v


class HomeownerRegistrationDTO(UserRegistrationBaseDTO):
    account_type: Literal[AccountType.HOMEOWNER] = AccountType.HOMEOWNER
    national_id: str
    date_of_birth: date

    @field_validator("national_id")
    @classmethod
    def validate_national_id(cls, v: str) -> str:
        if not NATIONAL_ID_RE.match(v):
            raise ValueError("national_id must be a valid 10-digit Saudi ID/Iqama")
        return v


class MerchantRegistrationDTO(UserRegistrationBaseDTO):
    account_type: Literal[AccountType.MERCHANT] = AccountType.MERCHANT
    business_name: str = Field(..., min_length=2, max_length=200)
    commercial_registration_number: str
    vat_number: Optional[str] = Field(default=None, max_length=20)
    authorized_signatory_name: str
    authorized_signatory_national_id: str

    @field_validator("commercial_registration_number")
    @classmethod
    def validate_cr_number(cls, v: str) -> str:
        if not CR_NUMBER_RE.match(v):
            raise ValueError("commercial_registration_number must be 10 digits")
        return v


UserRegistrationDTO = Union[HomeownerRegistrationDTO, MerchantRegistrationDTO]
```

### TypeScript interface

```typescript
export type AccountType = "HOMEOWNER" | "MERCHANT";

interface UserRegistrationBaseDTO {
  accountType: AccountType;
  fullName: string;
  email: string;
  phoneNumber: string;      // +966XXXXXXXXX
  password: string;
  splAddress: SPLAddressDTO;
  acceptedTermsAt: string;  // ISO-8601
}

export interface HomeownerRegistrationDTO extends UserRegistrationBaseDTO {
  accountType: "HOMEOWNER";
  nationalId: string;       // 10 digits
  dateOfBirth: string;      // ISO-8601 date
}

export interface MerchantRegistrationDTO extends UserRegistrationBaseDTO {
  accountType: "MERCHANT";
  businessName: string;
  commercialRegistrationNumber: string; // 10 digits
  vatNumber?: string | null;
  authorizedSignatoryName: string;
  authorizedSignatoryNationalId: string;
}

export type UserRegistrationDTO = HomeownerRegistrationDTO | MerchantRegistrationDTO;
```

### API response contract (post-submit)

```typescript
export interface UserRegistrationResponseDTO {
  userId: string;               // UUID
  status: "PENDING_APPROVAL";
  submittedAt: string;          // ISO-8601
  message: string;               // e.g. "Awaiting Superadmin review"
}
```

---

## 3. `HardwareAssignmentDTO` — Factory Admin Inventory Lock

Issued when a Factory Admin reserves a specific hardware unit for an Installation Job.
This DTO doubles as the **optimistic-lock request payload** — the backend must treat the
reservation as an atomic operation (see [database.md](./database.md) §"Transactional
Boundaries").

### Pydantic DTO

```python
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re

MAC_ADDRESS_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
SERIAL_NUMBER_RE = re.compile(r"^QBX-[A-Z0-9]{10}$")


class HardwareStatus(str, Enum):
    IN_INVENTORY = "IN_INVENTORY"
    STAGED = "STAGED"
    ASSIGNED = "ASSIGNED"
    PROVISIONING = "PROVISIONING"
    DIAGNOSTICS = "DIAGNOSTICS"
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    DEFECTIVE = "DEFECTIVE"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class HardwareAssignmentDTO(BaseModel):
    request_id: str                    # Installation request being fulfilled (UUID)
    hardware_unit_id: str               # Internal PK of the hardware unit (UUID)
    serial_number: str
    mac_address: str
    technician_id: str                  # UUID
    scheduled_window_start: datetime
    scheduled_window_end: datetime
    assigned_by: str                    # Factory Admin user ID (UUID)
    expected_hardware_status: HardwareStatus = HardwareStatus.STAGED
    version: int = Field(..., description="Optimistic-concurrency token read from the unit row")

    @field_validator("serial_number")
    @classmethod
    def validate_serial(cls, v: str) -> str:
        if not SERIAL_NUMBER_RE.match(v):
            raise ValueError("serial_number must match QBX-<10 alphanumeric>")
        return v

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str) -> str:
        v = v.upper()
        if not MAC_ADDRESS_RE.match(v):
            raise ValueError("mac_address must be colon-separated uppercase hex, e.g. AA:BB:CC:DD:EE:FF")
        return v

    @field_validator("scheduled_window_end")
    @classmethod
    def validate_window(cls, v: datetime, info) -> datetime:
        start = info.data.get("scheduled_window_start")
        if start and v <= start:
            raise ValueError("scheduled_window_end must be after scheduled_window_start")
        return v
```

### TypeScript interface

```typescript
export type HardwareStatus =
  | "IN_INVENTORY" | "STAGED" | "ASSIGNED" | "PROVISIONING"
  | "DIAGNOSTICS" | "ACTIVE" | "MAINTENANCE" | "DEFECTIVE"
  | "QUARANTINED" | "DECOMMISSIONED";

export interface HardwareAssignmentDTO {
  requestId: string;
  hardwareUnitId: string;
  serialNumber: string;        // QBX-<10 alphanumeric>
  macAddress: string;          // AA:BB:CC:DD:EE:FF
  technicianId: string;
  scheduledWindowStart: string; // ISO-8601
  scheduledWindowEnd: string;   // ISO-8601
  assignedBy: string;
  expectedHardwareStatus: HardwareStatus; // default "STAGED"
  version: number;              // optimistic-concurrency token
}
```

### Reservation response

```typescript
export interface HardwareAssignmentResultDTO {
  jobId: string;
  hardwareUnitId: string;
  status: "SCHEDULED" | "CONFLICT";
  // Present only when status === "CONFLICT" — the unit was reserved
  // concurrently by another Factory Admin between read and write.
  conflictReason?: string;
  currentVersion?: number;
}
```

---

## 4. `TechnicianDiagnosticPayloadDTO` — Hardware Pass/Fail Telemetry

Submitted by the mobile app (relayed via the Edge device) after the automated factory
diagnostic sequence. Each check reports independently so partial-failure debugging is
possible; the top-level `overall_result` is derived, never trusted from the client alone —
the backend recomputes it server-side from the individual `checks[]`.

### Pydantic DTO

```python
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class DiagnosticCheckType(str, Enum):
    SOLENOID_LOCK_CYCLE = "SOLENOID_LOCK_CYCLE"
    DOOR_POSITION_SENSOR = "DOOR_POSITION_SENSOR"
    STATUS_LED = "STATUS_LED"
    ACOUSTIC_BUZZER = "ACOUSTIC_BUZZER"
    CAMERA_STREAM_PRIMARY = "CAMERA_STREAM_PRIMARY"
    CAMERA_STREAM_SECONDARY = "CAMERA_STREAM_SECONDARY"
    MQTT_CONNECTIVITY = "MQTT_CONNECTIVITY"


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


class DiagnosticCheckDTO(BaseModel):
    check_type: DiagnosticCheckType
    result: CheckResult
    started_at: datetime
    completed_at: Optional[datetime] = None
    latency_ms: Optional[int] = Field(default=None, ge=0)
    metrics: dict = Field(default_factory=dict)
    # e.g. for CAMERA_STREAM_PRIMARY: {"resolution": "1080p", "fps": 24, "signal_dbm": -52}
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class TechnicianDiagnosticPayloadDTO(BaseModel):
    job_id: str
    hardware_unit_id: str
    technician_id: str
    run_number: int = Field(..., ge=1, description="Attempt count within this job")
    started_at: datetime
    completed_at: datetime
    checks: List[DiagnosticCheckDTO] = Field(..., min_length=1)
    firmware_version: str
    overall_result: Optional[CheckResult] = None  # server-computed; client value ignored

    @model_validator(mode="after")
    def compute_overall_result(self) -> "TechnicianDiagnosticPayloadDTO":
        if any(c.result in (CheckResult.FAIL, CheckResult.TIMEOUT) for c in self.checks):
            self.overall_result = CheckResult.FAIL
        elif any(c.result == CheckResult.SKIPPED for c in self.checks):
            self.overall_result = CheckResult.FAIL
        else:
            self.overall_result = CheckResult.PASS
        return self
```

### TypeScript interface

```typescript
export type DiagnosticCheckType =
  | "SOLENOID_LOCK_CYCLE" | "DOOR_POSITION_SENSOR" | "STATUS_LED"
  | "ACOUSTIC_BUZZER" | "CAMERA_STREAM_PRIMARY" | "CAMERA_STREAM_SECONDARY"
  | "MQTT_CONNECTIVITY";

export type CheckResult = "PASS" | "FAIL" | "TIMEOUT" | "SKIPPED";

export interface DiagnosticCheckDTO {
  checkType: DiagnosticCheckType;
  result: CheckResult;
  startedAt: string;
  completedAt?: string;
  latencyMs?: number;
  metrics: Record<string, unknown>;
  errorCode?: string;
  errorMessage?: string;
}

export interface TechnicianDiagnosticPayloadDTO {
  jobId: string;
  hardwareUnitId: string;
  technicianId: string;
  runNumber: number;
  startedAt: string;
  completedAt: string;
  checks: DiagnosticCheckDTO[];
  firmwareVersion: string;
  // overallResult is computed and returned by the server; do not trust a client-sent value
  overallResult?: CheckResult;
}
```

### Server response

```typescript
export interface DiagnosticSubmissionResultDTO {
  jobId: string;
  overallResult: CheckResult;
  nextAction:
    | "PROCEED_TO_PHOTO_SIGNATURE"   // PASS
    | "RETRY_AVAILABLE"               // FAIL, retries remain
    | "MARK_FAILED_DIAGNOSTIC";       // FAIL, retries exhausted
  retriesRemaining: number;
  failedChecks: DiagnosticCheckType[];
}
```

---

## 5. Cross-cutting conventions

- **Envelope**: all API responses wrap payloads as `{ data, error, meta }`; `error` follows
  RFC 7807 `application/problem+json` shape (`type`, `title`, `status`, `detail`, `instance`).
- **Idempotency**: mutating endpoints on the technician pipeline (`accept`, `checkin`,
  `verify-hardware`, `provisioning-complete`, `complete`) accept an `Idempotency-Key` header
  to safely tolerate mobile network retries.
- **Auth**: all endpoints except registration and login require `Authorization: Bearer
  <JWT>` issued via the OAuth 2.0 Authorization Code (web portals) or Password/Device
  Code (mobile app) grant, scoped by role (`homeowner`, `merchant`, `superadmin`,
  `factory_admin`, `technician`).
- **File uploads** (proof photo, signature) are pre-signed to object storage; the DTO only
  carries the resulting URL/object key, never raw binary in JSON payloads.
