# ADR 0002: Local sign-in with passwords for Engineer and Admin

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-01
- Decides: the product owner (Jay), until a tech lead joins
- Related: #9, #11; REQ-USR-001 to REQ-USR-008 in [stage1.md](../requirements/stage1.md)

## Context

The GUI spec (§8) gives Operators, Engineers and Admins different rights. In v0.1 anyone picks any user from a
list, with no password, and only the screens hide pages. So an audit entry such as "Engineer Kim raised the
threshold" proves nothing, and the Engineering standard requires the service layer to check the role on every
write and local passwords to be hashed with Argon2 or bcrypt. Stage 4 adds sign-in through the customer's MES
(GUI §5), and a station must keep working when the MES or network is down. Operators change often, may wear
gloves, and must never be stopped from inspecting by a sign-in screen.

## Decision

1. **Who signs in.** Engineers and Admins sign in with a name and password. Operators pick their name at the
   start of a shift; a station setting can add a 4 to 6 digit PIN. The Operator view never asks for a password.
2. **Hashing.** Argon2id, the variant RFC 9106 recommends, through argon2-cffi 25.1.0 with its default
   parameters, RFC 9106's low-memory profile: 3 passes, 64 MiB, 4 lanes, 16-byte salt, 32-byte hash. One check
   took about 95 ms on a cloud VM with 4 virtual CPUs at 2.1 GHz. Hashes carry their parameters, and a hash with
   old parameters is replaced at the next successful sign-in. PINs are hashed the same way.
3. **Password rules.** At least 15 characters, which NIST SP 800-63B-4 asks for when a password is the only
   factor. Up to 64 characters of any kind, Korean included, normalised to NFKC before hashing. No composition
   rules and no forced expiry. New passwords are checked against a bundled list of common passwords and the
   station's own user, company and product names. A customer profile may raise the minimum length.
4. **Lockout and idle (proposed numbers).** 5 failed sign-ins in a row lock that account for 5 minutes, and an
   Admin can unlock it sooner. After 15 minutes without input, an Engineer or Admin session returns to the
   Operator view with the shift's operator. A lock never stops the Operator view.
5. **Enforced in the service layer.** Every `AppContext` method that writes checks the signed-in role and raises
   a permission error with an AOI-USR code (catalogue in #4). Pages write only through `AppContext`, which #11
   makes true and a test keeps true, so no write escapes the check. Hiding a page is only a convenience.
6. **First Admin and recovery.** There is no default password. The first-run wizard creates the first Admin and
   shows a one-time recovery code, stored only as a hash, that lets that Admin set a new password. A lost
   password and code are fixed by a Windows administrator running the installer's repair, which creates a new
   Admin and writes an audit entry. The app does not try to defend itself against a Windows administrator.
7. **Records.** A user is a UUID, name, role, password or PIN hash, status (active or disabled), failed-attempt
   count and lock time, with times in UTC ISO 8601. In daily use users are disabled rather than deleted, so past
   records keep their names. When a person asks, an Admin exports their records and removes the account, and
   past records keep only a pseudonymous operator ID (LEG Privacy, REQ-USR-008). Sign-ins, failures, locks,
   unlocks, resets and user changes go to the audit trail, never with the secret. The table changes through a
   numbered migration, after #2.
8. **Stage 4.** MES sign-in becomes a second provider behind the same `AppContext` calls, and local accounts stay
   as the fallback when the MES cannot be reached.

## Alternatives considered

- **Windows accounts.** Many stations share one Windows login, and some sites have no domain. Kept as a later
  option for the Enterprise edition.
- **bcrypt.** Allowed by the standard, but it truncates passwords at 72 bytes, which long Korean passphrases can
  reach. Argon2id has no such limit.
- **Passwords for Operators too.** They would slow every shift change and tempt people to share one account.
  The optional PIN covers sites that want more.

## Consequences

- New dependencies, each pinned and listed in the SBOM: argon2-cffi 25.1.0 (MIT), argon2-cffi-bindings 26.1.0
  (MIT), cffi 2.1.1 (MIT-0) and pycparser 3.0 (BSD-3-Clause). MIT-0 is MIT without the duty to keep the notice,
  so it asks less of us, but the Legal standard's allowed list does not name it; adding it is Jay's decision, and
  this work waits for it. The Argon2 C code inside the bindings is CC0-1.0 or Apache-2.0 upstream, and we take
  it under Apache-2.0, which the list allows. The common-password list needs an allowed license too; the
  license check confirms all of them.
- Until REQ-USR-002 ships at 1.0, the G1 build keeps v0.1's user picker, so its audit entries record a picked
  name and, as the Context says, prove nothing about who acted. The G1 validation report says so.
- One migration for the users table, so this work waits for #2.
- New screens need sketches first: the sign-in dialog, user management in Settings and the first-run wizard.
- The manual gains sign-in, lockout and recovery. The demo workspace has its own Engineer account, whose
  passphrase is generated afresh at each demo reset and shown to the presenter, so no fixed password ships.
- Tests: hashing and rehashing, lockout and idle timing with a fake clock, and a role check on every `AppContext`
  write.
