# QBox Shared Contracts

This directory is the only workspace-level bridge between `Qbox-Backend` and `Qbox-Hardware`.

The repositories are independent Git repositories. Do not share implementation code between them. When both repositories need to agree on behavior, document the interface here and implement each side inside its owning repository.

## Active Contracts

- `device-onboarding/v1.md` - first-boot registration, bootstrap credentials, certificate issuance, early configuration, and MQTT setup.
- `mqtt/device-control-plane-v1.md` - canonical MQTT topic namespace and envelope requirements.
- `connectivity/v1.md` - production connectivity boundary for backend authorization/state/audit, device-side BLE/Wi-Fi/NetworkManager behavior, and MQTT connectivity events/commands.

## Proposed Contracts

- `api/locker-device-v2.md` - PROPOSAL (not approved; do not implement until the hardware repository approves): Ed25519-signed one-time access tokens with offline verification, device keys, batched door events, HTTPS command fallback, offline sync, evidence upload, multi-compartment state; v1 stays supported in parallel.

## Versioning Rules

- Additive fields are backward compatible when consumers can ignore unknown fields.
- Removing fields, changing enum meanings, changing authentication requirements, or changing topic/endpoint semantics is breaking.
- Breaking changes require a new versioned contract document.
- Repository code must reference contracts by behavior and schema, not by importing files from the other repository.

