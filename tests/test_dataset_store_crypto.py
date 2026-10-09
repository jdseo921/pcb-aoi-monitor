"""REQ-TRN-017 (stage S38; ADR 0010): file format 1 of a customer's dataset store, its key's check value and recovery
sheet, and the key store behind them."""

from __future__ import annotations

import sys
import uuid

import pytest

from aoi.core import crypto
from aoi.data import credentials

STORE = "6f1c2a52-2a45-4a43-9a7e-0d6f0e7c1b11"
PATH = "images/CAL-1/OK/board_001.png"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


def test_req_trn_017_format_1_round_trip_and_refusals() -> None:
    """A file encrypts to 50 bytes more, never holds the plain bytes, and opens only under its own key, key id, store
    and path: a changed byte, a moved or swapped file, another store's file, a wrong key and a plain file are refused,
    each with its reason."""
    key, key_id = crypto.new_key()
    blob = crypto.encrypt(key, key_id, STORE, PATH, PNG)
    assert len(blob) == len(PNG) + 50 and blob[:4] == b"AOIE" and PNG[:64] not in blob
    assert crypto.header(blob) == crypto.Header(key_id, blob[22:34])  # magic, format, algorithm, key id, nonce
    assert crypto.decrypt(key, key_id, STORE, PATH, blob) == PNG
    assert crypto.encrypt(key, key_id, STORE, PATH, PNG) != blob  # a new nonce each time
    changed = bytearray(blob)
    changed[40] ^= 1
    other_key, other_id = crypto.new_key()
    cases = {
        "changed": (key, key_id, STORE, PATH, bytes(changed)),
        "moved": (key, key_id, STORE, "images/CAL-1/OK/board_002.png", blob),
        "Windows separators": (key, key_id, STORE, PATH.replace("/", "\\"), blob),
        "other store": (key, key_id, str(uuid.uuid4()), PATH, blob),
        "other key id": (other_key, other_id, STORE, PATH, blob),
        "wrong key": (other_key, key_id, STORE, PATH, blob),
        "plain": (key, key_id, STORE, PATH, PNG),
    }
    reasons = {}
    for case, args in cases.items():
        try:
            reasons[case] = crypto.decrypt(*args) == PNG and "opened"
        except crypto.NotOpened as e:
            reasons[case] = str(e.reason.fill(file="x.png"))
    damaged = "x.png was changed, moved or damaged since it was written"
    assert reasons == {
        "changed": damaged,
        "moved": damaged,
        "Windows separators": "opened",  # a path as Windows writes it is the same path
        "other store": damaged,
        "other key id": "x.png is encrypted under another store's key",
        "wrong key": damaged,
        "plain": "x.png is not encrypted",
    }


def test_req_trn_017_recovery_sheet_and_check_value() -> None:
    """The sheet gives the key back as typed, in any case and spacing; a key one letter off gives another check value,
    and text that is not 52 base32 characters gives none."""
    key, _ = crypto.new_key()
    printed = crypto.sheet(key)
    groups = printed.split(" ")
    assert len(groups) == 13 and all(len(g) == 4 for g in groups)
    assert crypto.key_from_sheet(printed) == key
    assert crypto.key_from_sheet(printed.lower().replace(" ", "-")) == key
    typo = ("B" if printed[0] != "B" else "C") + printed[1:]
    wrong = crypto.key_from_sheet(typo)
    assert wrong is not None and crypto.check_value(wrong) != crypto.check_value(key)
    assert crypto.check_value(key) == crypto.check_value(bytes(key)) and len(crypto.check_value(key)) == 64
    assert crypto.key_from_sheet(printed[:-1]) is None and crypto.key_from_sheet("1" * 52) is None


def test_req_trn_017_memory_key_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key store's three calls: a secret written reads back, a second write replaces it, and a deleted one reads
    None; deleting it again says there was nothing. Off Windows the app's own key store is the one in memory."""
    monkeypatch.undo()  # the suite's key store for each test (conftest's `keys`) set aside
    keys = credentials.MemoryCredentials()
    name = credentials.STORE_PREFIX + STORE
    assert keys.read(name) is None
    keys.write(name, b"one")
    keys.write(name, b"two")
    assert keys.read(name) == b"two"
    assert keys.delete(name) is True and keys.read(name) is None and keys.delete(name) is False
    if sys.platform != "win32":  # elsewhere the app keeps its keys in memory, gone when the process ends
        assert credentials.default() is credentials.MEMORY


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager exists only on Windows")
def test_req_trn_017_windows_credential_manager() -> None:
    """On Windows the key goes to Credential Manager and comes back byte for byte, and is gone once deleted."""
    keys = credentials.WindowsCredentials()
    name = f"{credentials.STORE_PREFIX}test-{uuid.uuid4()}"
    secret, _ = crypto.new_key()
    try:
        assert keys.read(name) is None
        keys.write(name, secret)
        assert keys.read(name) == secret
    finally:
        deleted = keys.delete(name)
    assert deleted is True and keys.read(name) is None and keys.delete(name) is False
