from __future__ import annotations

import json
from typing import Any

# Statuses that map to a passing OpenHTF measurement outcome. Every other
# TestResultStatus value (FAIL/TIMEOUT/BLOCKED/NOT_EXECUTABLE/
# REQUIRES_HUMAN/REQUIRES_EXTERNAL_EQUIPMENT/...) is recorded as-is, never
# silently upgraded - see phases.py's PhaseResult mapping for how each of
# these affects run continuation.
_PASSING_STATUSES = {"PASS", "WARN"}


def record_step_result(test, step: dict, result_payload: dict[str, Any]) -> str:
    """
    Records one generic 'step_outcome' measurement plus the full raw result
    payload as a JSON attachment. Deliberately generic (one measurement, one
    attachment) rather than decoding 19 different per-step-type numeric
    measurement schemas - a future pass can add per-type measurement
    decoding without touching the phase/plan machinery this depends on.
    Returns the resolved status string for the caller's PhaseResult mapping.
    """
    status = str(result_payload.get("status") or "FAIL").upper()
    test.measurements["step_outcome"] = status
    test.attach(
        f"{step.get('step_type', 'step')}_result.json",
        json.dumps(result_payload, default=str).encode("utf-8"),
        mimetype="application/json",
    )
    return status


def is_passing(status: str) -> bool:
    return status in _PASSING_STATUSES
