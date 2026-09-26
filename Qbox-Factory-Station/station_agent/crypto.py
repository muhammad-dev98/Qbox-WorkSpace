from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Client-side mirror of Qbox-Hardware's BLESecureSession
# (platform/qbox_platform/bluetooth/secure_protocol.py). Deliberately not a
# shared import across repos (the station agent is a separate deployable
# with its own lifecycle) - but uses the exact same `cryptography` primitives
# and byte layout, so there is no WebCrypto-vs-cryptography translation risk
# the previous browser implementation carried. The device generates its own
# random session_id in BLESecureSession.establish() and returns it in the
# authorize response (secure_session_id) - this class never generates one of
# its own, it adopts the device's.


def compute_nonces(*, session_id: str, token: str, expires_at: str) -> tuple[bytes, bytes]:
    device_nonce = hashlib.sha256(f"{session_id}:{expires_at}".encode("utf-8")).digest()[:16]
    client_nonce = hashlib.sha256(token.encode("utf-8")).digest()[:16]
    return device_nonce, client_nonce


def derive_session_key(*, token: str, device_nonce: bytes, client_nonce: bytes) -> bytes:
    if len(token) < 24:
        raise ValueError("QBOX_BLE_TOKEN_TOO_SHORT")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=device_nonce + client_nonce,
        info=b"qbox-ble-provisioning-v1",
    ).derive(token.encode("utf-8"))


@dataclass
class ClientSecureSession:
    session_id: str
    key: bytes
    send_sequence: int = 0
    highest_received_sequence: int = 0
    received_sequences: set[int] = field(default_factory=set)

    @classmethod
    def from_authorize_response(cls, *, secure_session_id: str, token: str, session_id: str, expires_at: str) -> "ClientSecureSession":
        device_nonce, client_nonce = compute_nonces(session_id=session_id, token=token, expires_at=expires_at)
        key = derive_session_key(token=token, device_nonce=device_nonce, client_nonce=client_nonce)
        return cls(session_id=secure_session_id, key=key)

    def encrypt(self, payload: bytes, *, aad: bytes = b"") -> dict[str, Any]:
        self.send_sequence += 1
        nonce = os.urandom(4) + self.send_sequence.to_bytes(8, "big")
        ciphertext = AESGCM(self.key).encrypt(nonce, payload, aad)
        return {
            "session_id": self.session_id,
            "sequence": self.send_sequence,
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }

    def decrypt(self, frame: dict[str, Any], *, aad: bytes = b"") -> bytes:
        if str(frame.get("session_id")) != self.session_id:
            raise PermissionError("QBOX_BLE_SESSION_MISMATCH")
        sequence = int(frame.get("sequence") or 0)
        if sequence <= 0 or sequence in self.received_sequences or sequence <= self.highest_received_sequence:
            raise PermissionError("QBOX_BLE_REPLAY_REJECTED")
        nonce = _unb64(str(frame.get("nonce") or ""))
        ciphertext = _unb64(str(frame.get("ciphertext") or ""))
        plaintext = AESGCM(self.key).decrypt(nonce, ciphertext, aad)
        self.received_sequences.add(sequence)
        self.highest_received_sequence = max(self.highest_received_sequence, sequence)
        return plaintext


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    import base64

    return base64.b64decode(value.encode("ascii"), validate=True)


def _now_epoch() -> float:
    return time.time()


def new_request_id() -> str:
    return str(uuid.uuid4())
