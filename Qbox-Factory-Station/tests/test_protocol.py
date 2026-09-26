from __future__ import annotations

import time

import pytest

from station_agent.protocol import BLEReassembler, chunk_message


def test_chunk_and_reassemble_roundtrip():
    payload = b"x" * 500
    chunks = chunk_message(payload, mtu=96, message_id="message-1")
    reassembler = BLEReassembler()

    result = None
    for chunk in chunks:
        result = reassembler.add(chunk)

    assert result == payload


def test_reassembles_out_of_order_and_ignores_duplicates():
    payload = b"hello world" * 20
    chunks = chunk_message(payload, mtu=32, message_id="message-2")
    reassembler = BLEReassembler()

    assert reassembler.add(chunks[1]) is None
    assert reassembler.add(chunks[1]) is None  # duplicate, ignored
    assert reassembler.add(chunks[0]) is None
    result = None
    for chunk in chunks[2:]:
        result = reassembler.add(chunk)

    assert result == payload


def test_rejects_a_tampered_chunk_digest():
    chunks = chunk_message(b"real payload", mtu=64, message_id="message-3")
    chunks[0]["payload"] = chunks[0]["payload"][:-2] + "AA"
    reassembler = BLEReassembler()

    with pytest.raises(ValueError, match="QBOX_BLE_CHUNK_DIGEST_MISMATCH"):
        reassembler.add(chunks[0])


def test_timeout_is_measured_per_message_not_per_object(monkeypatch):
    current_time = {"value": 1_000_000.0}
    monkeypatch.setattr(time, "time", lambda: current_time["value"])

    reassembler = BLEReassembler()
    current_time["value"] += 45  # connection idle for 45s before any message is sent

    chunks = chunk_message(b"a message sent well after the reassembler was created", mtu=32, message_id="late-message")
    result = None
    for chunk in chunks:
        result = reassembler.add(chunk)

    assert result == b"a message sent well after the reassembler was created"


def test_rejects_a_message_larger_than_the_safe_cap():
    from station_agent.protocol import MAX_REASSEMBLED_MESSAGE_BYTES

    oversized_chunk_count = (MAX_REASSEMBLED_MESSAGE_BYTES // 100) + 10
    chunks = chunk_message(b"x" * (oversized_chunk_count * 100), mtu=100, message_id="oversized")
    reassembler = BLEReassembler()

    with pytest.raises(ValueError, match="QBOX_BLE_MESSAGE_TOO_LARGE"):
        for chunk in chunks:
            reassembler.add(chunk)
