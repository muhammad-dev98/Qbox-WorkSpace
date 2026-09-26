from __future__ import annotations

import time

import pytest

from station_agent.crypto import ClientSecureSession, compute_nonces, derive_session_key


def test_compute_nonces_matches_device_derivation(device_secure_protocol):
    session_id, token, expires_at = "session-abc", "token-value-with-enough-entropy", "2026-01-01T00:00:00+00:00"

    device_nonce, client_nonce = compute_nonces(session_id=session_id, token=token, expires_at=expires_at)

    expected_device_nonce = device_secure_protocol.hashlib.sha256(f"{session_id}:{expires_at}".encode("utf-8")).digest()[:16]
    expected_client_nonce = device_secure_protocol.hashlib.sha256(token.encode("utf-8")).digest()[:16]
    assert device_nonce == expected_device_nonce
    assert client_nonce == expected_client_nonce


def test_client_and_device_derive_the_identical_session_key(device_secure_protocol):
    token = "token-value-with-enough-entropy"
    device_nonce = b"0123456789abcdef"
    client_nonce = b"fedcba9876543210"

    client_key = derive_session_key(token=token, device_nonce=device_nonce, client_nonce=client_nonce)

    device_session = device_secure_protocol.BLESecureSession.establish(
        token=token, device_nonce=device_nonce, client_nonce=client_nonce, expires_at_epoch=time.time() + 60
    )
    assert client_key == device_session.key


def test_full_roundtrip_against_the_real_device_session_object(device_secure_protocol):
    # The strongest possible test: encrypt with the device's real
    # BLESecureSession, decrypt with this station agent's independent
    # ClientSecureSession, and back again - proving genuine wire
    # compatibility, not just that the two derive the same key bytes.
    token = "token-value-with-enough-entropy"
    session_id, expires_at = "session-xyz", "2026-01-01T00:00:00+00:00"
    device_nonce, client_nonce = compute_nonces(session_id=session_id, token=token, expires_at=expires_at)

    device_session = device_secure_protocol.BLESecureSession.establish(
        token=token, device_nonce=device_nonce, client_nonce=client_nonce, expires_at_epoch=time.time() + 60
    )
    client_session = ClientSecureSession.from_authorize_response(
        secure_session_id=device_session.session_id, token=token, session_id=session_id, expires_at=expires_at
    )

    device_frame = device_session.encrypt(b'{"action":"wifi.scan"}')
    assert client_session.decrypt(device_frame) == b'{"action":"wifi.scan"}'

    client_frame = client_session.encrypt(b'{"networks":[]}')
    assert device_session.decrypt(client_frame) == b'{"networks":[]}'


def test_replay_is_rejected(device_secure_protocol):
    token = "token-value-with-enough-entropy"
    session_id, expires_at = "session-replay", "2026-01-01T00:00:00+00:00"
    device_nonce, client_nonce = compute_nonces(session_id=session_id, token=token, expires_at=expires_at)
    device_session = device_secure_protocol.BLESecureSession.establish(
        token=token, device_nonce=device_nonce, client_nonce=client_nonce, expires_at_epoch=time.time() + 60
    )
    client_session = ClientSecureSession.from_authorize_response(
        secure_session_id=device_session.session_id, token=token, session_id=session_id, expires_at=expires_at
    )

    frame = device_session.encrypt(b"once")
    client_session.decrypt(frame)
    with pytest.raises(PermissionError, match="QBOX_BLE_REPLAY_REJECTED"):
        client_session.decrypt(frame)
