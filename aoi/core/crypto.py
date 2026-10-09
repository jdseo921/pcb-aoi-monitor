"""A customer's dataset store, encrypted at rest (REQ-TRN-017; stage S38; ADR 0010): file format 1, its key, the key's
check value and its recovery sheet. No Qt; the key itself is kept by `aoi.data.credentials`, never here.

Format 1 is a 34-byte header, then the AES-256-GCM ciphertext and its 16-byte tag. The header holds the magic `AOIE`,
the format, the algorithm, the store's 16-byte key id and a 96-bit nonce from `os.urandom`. The associated data is the
header, the store's UUID and the file's workspace-relative path as the rows store it, so a file moved, swapped with
another or put into another store does not open."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..errors import QT_TRANSLATE_NOOP, Phrase

MAGIC = b"AOIE"
FORMAT = 1
AES_256_GCM = 1
HEADER = struct.Struct(">4sBB16s12s")  # magic, format, algorithm, key id, nonce: 34 bytes
TAG_BYTES = 16
KEY_BYTES = 32
KEY_ID_BYTES = 16
CHECK_TEXT = b"AOI dataset store check, format 1"  # what the check value is an HMAC-SHA-256 of


NOT_ENCRYPTED = QT_TRANSLATE_NOOP("Errors", "{file} is not encrypted")
OTHER_KEY = QT_TRANSLATE_NOOP("Errors", "{file} is encrypted under another store's key")
DAMAGED = QT_TRANSLATE_NOOP("Errors", "{file} was changed, moved or damaged since it was written")


class NotOpened(Exception):
    """A store's file that does not open: `reason` says why, with {file} for the caller to fill."""

    def __init__(self, reason: Phrase) -> None:
        super().__init__(str(reason))
        self.reason = reason


@dataclass(frozen=True)
class Header:
    key_id: bytes
    nonce: bytes


def new_key() -> tuple[bytes, bytes]:
    """A store's random 256-bit key and its random 16-byte key id."""
    return os.urandom(KEY_BYTES), os.urandom(KEY_ID_BYTES)


def check_value(key: bytes) -> str:
    """The HMAC-SHA-256 of CHECK_TEXT under `key`, in hex: stored with the store, it tells a key typed from the sheet,
    or read from the key store, from a wrong one without opening a file."""
    return hmac.new(key, CHECK_TEXT, hashlib.sha256).hexdigest()


def header(blob: bytes) -> Header | None:
    """The header of a format-1 file, or None for bytes that do not start with one (a plain file)."""
    if len(blob) < HEADER.size + TAG_BYTES or not blob.startswith(MAGIC):
        return None
    magic, version, algorithm, key_id, nonce = HEADER.unpack_from(blob)
    if (version, algorithm) != (FORMAT, AES_256_GCM):
        return None
    return Header(key_id, nonce)


def _associated(head: bytes, store_uuid: str, path: str) -> bytes:
    return head + store_uuid.encode("ascii") + b"\0" + path.replace("\\", "/").encode("utf-8")


def encrypt(key: bytes, key_id: bytes, store_uuid: str, path: str, data: bytes) -> bytes:
    """`data` as a format-1 file of the store at the workspace-relative `path`: 50 bytes longer."""
    head = HEADER.pack(MAGIC, FORMAT, AES_256_GCM, key_id, os.urandom(12))
    return head + AESGCM(key).encrypt(head[-12:], data, _associated(head, store_uuid, path))


def decrypt(key: bytes, key_id: bytes, store_uuid: str, path: str, blob: bytes) -> bytes:
    """The plain bytes of a format-1 file of the store at `path`; NotOpened for a file with no header (never read as
    plain), another store's key id, or a tag that fails: a changed byte, a moved or swapped file, a wrong key."""
    found = header(blob)
    if found is None:
        raise NotOpened(NOT_ENCRYPTED)
    if found.key_id != key_id:
        raise NotOpened(OTHER_KEY)
    head = blob[: HEADER.size]
    try:
        return AESGCM(key).decrypt(found.nonce, blob[HEADER.size :], _associated(head, store_uuid, path))
    except InvalidTag:
        raise NotOpened(DAMAGED) from None


def sheet(key: bytes) -> str:
    """The key as the recovery sheet prints it: 52 base32 letters and digits in groups of four."""
    text = base64.b32encode(key).decode("ascii").rstrip("=")
    return " ".join(text[i : i + 4] for i in range(0, len(text), 4))


def key_from_sheet(text: str) -> bytes | None:
    """The key a recovery sheet's text gives, spaces, hyphens and case aside; None when it is not 52 base32 characters
    (the check value then tells a wrong one)."""
    letters = "".join(c for c in text.upper() if c not in " -\t\n")
    if len(letters) != 52:
        return None
    try:
        key = base64.b32decode(letters + "====")
    except ValueError:
        return None
    return key if len(key) == KEY_BYTES else None
