from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Mirrors Qbox-Hardware's BLEChunk/chunk_message/BLEReassembler
# (platform/qbox_platform/bluetooth/secure_protocol.py) exactly - a pure,
# symmetric wire format with no device-specific state, so both sides can
# implement it independently without sharing a package.

OUTBOUND_CHUNK_MTU = 150


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


@dataclass(frozen=True)
class BLEChunk:
    message_id: str
    chunk_index: int
    total_chunks: int
    payload: bytes

    def as_wire(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "payload": _b64(self.payload),
            "digest": hashlib.sha256(self.payload).hexdigest(),
        }

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> "BLEChunk":
        payload = _unb64(str(value.get("payload") or ""))
        digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(digest, str(value.get("digest") or "")):
            raise ValueError("QBOX_BLE_CHUNK_DIGEST_MISMATCH")
        return cls(
            message_id=str(value["message_id"]),
            chunk_index=int(value["chunk_index"]),
            total_chunks=int(value["total_chunks"]),
            payload=payload,
        )


def chunk_message(payload: bytes, *, mtu: int = OUTBOUND_CHUNK_MTU, message_id: str | None = None) -> list[dict[str, Any]]:
    usable = max(1, mtu - 64)
    chunks = [payload[index : index + usable] for index in range(0, len(payload), usable)] or [b""]
    identifier = message_id or str(uuid.uuid4())
    return [
        BLEChunk(message_id=identifier, chunk_index=index, total_chunks=len(chunks), payload=chunk).as_wire()
        for index, chunk in enumerate(chunks)
    ]


MAX_REASSEMBLED_MESSAGE_BYTES = 65_536


@dataclass
class BLEReassembler:
    # Timeout tracked per message_id, not per object - see the identical
    # fix (and its rationale) in Qbox-Hardware's secure_protocol.py, applied
    # the same day this station agent's copy was written with the same bug.
    timeout_seconds: int = 30
    chunks: dict[str, dict[int, BLEChunk]] = field(default_factory=dict)
    _started_at: dict[str, float] = field(default_factory=dict)

    def add(self, wire_chunk: dict[str, Any]) -> bytes | None:
        chunk = BLEChunk.from_wire(wire_chunk)
        if chunk.total_chunks <= 0 or chunk.chunk_index < 0 or chunk.chunk_index >= chunk.total_chunks:
            raise ValueError("QBOX_BLE_INVALID_CHUNK_INDEX")
        now = time.time()
        started_at = self._started_at.setdefault(chunk.message_id, now)
        if now > started_at + self.timeout_seconds:
            self.chunks.pop(chunk.message_id, None)
            self._started_at.pop(chunk.message_id, None)
            raise TimeoutError("QBOX_BLE_REASSEMBLY_TIMEOUT")
        message_chunks = self.chunks.setdefault(chunk.message_id, {})
        message_chunks.setdefault(chunk.chunk_index, chunk)
        buffered_bytes = sum(len(c.payload) for c in message_chunks.values())
        if buffered_bytes > MAX_REASSEMBLED_MESSAGE_BYTES:
            self.chunks.pop(chunk.message_id, None)
            self._started_at.pop(chunk.message_id, None)
            raise ValueError("QBOX_BLE_MESSAGE_TOO_LARGE")
        if len(message_chunks) != chunk.total_chunks:
            return None
        ordered = [message_chunks[index].payload for index in range(chunk.total_chunks)]
        self.chunks.pop(chunk.message_id, None)
        self._started_at.pop(chunk.message_id, None)
        return b"".join(ordered)
