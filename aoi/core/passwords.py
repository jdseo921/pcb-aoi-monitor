"""Passwords and PINs (REQ-USR-002; ADR 0002, decisions 2 and 3). A secret is stored only as an Argon2id hash with
RFC 9106's low-memory profile (3 passes, 64 MiB, 4 lanes, 16-byte salt, 32-byte
hash), of its text normalised to NFKC, so a Korean passphrase typed with another input method still matches. A hash
carries its parameters; one made with older ones is `stale` and replaced at the next successful sign-in. A new password
is 15 to 64 characters of any kind, with no composition rule and no expiry, and is not a user's name, a customer's or
the product's, nor the demo workspace's published Admin password; a PIN is 4 to 6 digits. Neither the secret nor its
hash is ever logged, audited or exported. No Qt here.

Not yet (ADR 0002, decision 3): the bundled list of common passwords, which waits for a list under an allowed licence.
"""

from __future__ import annotations

import math
import secrets
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import cache

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError

from ..config import APP_NAME
from ..errors import QT_TRANSLATE_NOOP, Phrase

MIN_LENGTH, MAX_LENGTH = 15, 64  # NIST SP 800-63B-4 asks for 15 where a password is the only factor
PIN_DIGITS = range(4, 7)
DEMO_ADMIN = "show the demo to the customer"  # the demo workspace's Admin's, published: docs/demo/README.md
_HASHER = PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)  # Argon2id; named, not the library's default

TOO_SHORT = QT_TRANSLATE_NOOP("Errors", "is shorter than {length} characters")
TOO_LONG = QT_TRANSLATE_NOOP("Errors", "is longer than {length} characters")
A_NAME = QT_TRANSLATE_NOOP("Errors", "is the name of a user, a customer or the product")
PUBLISHED = QT_TRANSLATE_NOOP("Errors", "is the demo workspace's published password")
NOT_A_PIN = QT_TRANSLATE_NOOP("Errors", "is not 4 to 6 digits")


def normal(secret: str) -> str:
    """The secret as it is hashed: NFKC, so the same text typed two ways is one secret."""
    return unicodedata.normalize("NFKC", secret)


def hash_secret(secret: str) -> str:
    """The Argon2id hash of `secret`, with a new random salt and its parameters in the string."""
    return _HASHER.hash(normal(secret))


@cache
def _absent() -> str:
    """A hash to verify against when an account has none, made once, when first needed, not at import."""
    return _HASHER.hash("no password")


def verify(stored: str | None, secret: str) -> bool:
    """Whether `secret` is the one `stored` hashes; False for no hash or one that cannot be read. No hash takes as
    long as a wrong secret, so the time a refusal takes does not say which accounts have a password."""
    try:
        if not stored:
            _HASHER.verify(_absent(), normal(secret))  # for its time only: the answer is False whatever it says
            return False
        return bool(_HASHER.verify(stored, normal(secret)))
    except (VerificationError, InvalidHashError):
        return False


def stale(stored: str) -> bool:
    """Whether `stored` was made with other parameters than today's, so a sign-in that verified it hashes again; a
    hash that cannot be read is stale too."""
    try:
        return bool(_HASHER.check_needs_rehash(stored))
    except InvalidHashError:
        return True


def refusal(password: str, names: Iterable[str]) -> Phrase | None:
    """Why `password` cannot be a new password, or None when it can. `names`: the station's users and customers. The
    demo's published Admin password (`DEMO_ADMIN`) never is, whatever its case, spaces or marks between the words, in
    the demo or not: anyone may read it, and a start outside the demo puts an Admin who has it back in set-up
    (`AppContext._demo_admin`), which on a station with no other Admin leaves the Admin's password to whoever claims it
    next (senior review 2026-11-06, SEC-1)."""
    text = normal(password)
    if len(text) < MIN_LENGTH:
        return TOO_SHORT.fill(length=MIN_LENGTH)
    if len(text) > MAX_LENGTH:
        return TOO_LONG.fill(length=MAX_LENGTH)
    folded = text.casefold().replace(" ", "")
    if folded in {normal(n).casefold().replace(" ", "") for n in (*names, APP_NAME)}:
        return A_NAME
    if _letters(folded) == _letters(normal(DEMO_ADMIN).casefold()):
        return PUBLISHED
    return None


def _letters(text: str) -> str:
    """Only the letters and digits of `text`, so "show-the-demo" and "show the demo." read as "showthedemo"."""
    return "".join(c for c in text if c.isalnum())


def pin_refusal(pin: str) -> Phrase | None:
    """Why `pin` cannot be an Operator's PIN, or None when it can."""
    text = normal(pin)
    return None if text.isascii() and text.isdigit() and len(text) in PIN_DIGITS else NOT_A_PIN


CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32, none read as another (no I, O, 0 or 1): 5 bits each


def recovery_code() -> str:
    """A new one-time recovery code: 25 random letters and digits (125 bits) in five groups of five (REQ-USR-005)."""
    letters = "".join(secrets.choice(CODE_LETTERS) for _ in range(25))
    return " ".join(letters[i : i + 5] for i in range(0, 25, 5))


def code_text(code: str) -> str:
    """A recovery code as it is hashed: its letters and digits in capitals, whatever spaces or dashes were typed."""
    return "".join(c for c in normal(code).upper() if c.isalnum())


UNTIL_UNLOCKED = "9999-12-31T00:00:00+00:00"  # a lock only an Admin ends: after GUESS_LIMIT wrong passwords
GUESS_LIMIT = 100  # wrong passwords before that, not reset by a timed lock (NIST SP 800-63B-4, rate limiting)
FOR_GOOD = 60 * 24 * 365  # minutes beyond which a lock reads as until an Admin unlocks it


def locked_minutes(until: str | None) -> int:
    """The whole minutes left, rounded up, of a lock ending at `until` (UTC ISO 8601; with no offset, read as UTC);
    0 with none or once it ended. A time that cannot be read is a lock until an Admin unlocks it, never an error."""
    if not until:
        return 0
    try:
        end = datetime.fromisoformat(until)
    except ValueError:
        return FOR_GOOD + 1
    left = ((end if end.tzinfo else end.replace(tzinfo=UTC)) - datetime.now(UTC)).total_seconds()
    return max(0, math.ceil(left / 60))
