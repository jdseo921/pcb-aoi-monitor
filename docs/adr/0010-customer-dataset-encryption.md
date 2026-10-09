# ADR 0010: How each customer's dataset store is encrypted at rest

- Status: Proposed. Jay's merge of this record accepts it. Jay delegated the decision on 2026-10-09, so this record
  recommends one option.
- Date: 2026-10-09
- Decides: the product owner (Jay), until a tech lead joins
- Related: stages S37 (this record) and S38 (the build) of the Stage 1 plan; REQ-TRN-017, REQ-TRN-007, REQ-SET-010;
  [ADR 0002](0002-local-sign-in.md), [ADR 0003](0003-dependency-pinning.md),
  [ADR 0009](0009-labels-checks-and-dataset-versions.md); sketch `docs/sketches/training-datasets.md` (Q40, AOI-TRN-025)

## Context

REQ-TRN-017 keeps each customer's datasets in their own store, "encrypted at rest, by a method a design record
chooses". The rules that bind the method:

- Engineering: AI models and data, Customer data (MUST), "One encrypted dataset store per customer, and a training run
  reads from exactly one"; Security, Customer data (MUST), "Customer datasets are kept per customer, encrypted on our
  laptops with BitLocker, and returned or deleted when the engagement ends"; Secrets (MUST), "MES tokens and license
  keys sit in Windows Credential Manager, never in `settings.json` or logs"; Offline and least privilege (MUST), "No
  network call happens until a feature that needs one (updates, MES, telemetry) is switched on in Settings" and "The
  app runs as a standard Windows user, and only the installer needs admin rights".
- Legal: Deletion (MUST), "At the end of an engagement, or on request, the customer's images, labels and derived models
  are deleted from our machines within 30 days (proposed), and we confirm it in writing. What runs on their own
  stations stays theirs"; Privacy, "Data on a station belongs to the customer"; Licenses, MIT, BSD and Apache 2.0 are
  allowed ("Keep copyright notices and license texts, plus Apache NOTICE files"), and "CI builds the third-party list
  from the SBOM and fails on a forbidden or unknown license". The Charter's checklist: "Every new dependency has an
  allowed license and a pinned version."

Stations run Windows 11 IoT Enterprise LTSC 2024 or Windows 11 Pro 25H2, offline, with one workspace folder; people
sign in through the app (ADR 0002) and may share one Windows account; CI tests on Linux and Windows.
`imaging._read_image` reads a sample file whole, then `cv2.imdecode`; `AppContext.train` reads each OK and NG file once
per run; frozen versions name files by workspace-relative path and SHA-256 in append-only rows (ADR 0009).

## Decision

1. **Per-customer AES-256-GCM in the app (option b), with the `cryptography` package.** A store is a record with a
   UUID, its customer and one random 256-bit key. Every board model belongs to one store (our own and synthetic boards
   get a store of their own), and every sample file and frozen manifest of its board models is written encrypted under
   that key. BitLocker stays the baseline for the whole disk: required on our laptops by the Security rule, advised in
   the installation guide for customer stations, never relied on by the app.
2. **One key per store, not per station.** A station holds the keys of the stores in its workspace. A per-station key,
   the direction Q40 first took, could not shred one customer alone, and one recovery sheet would open every customer
   on a laptop of ours.
3. **The key sits in Windows Credential Manager, reached through ctypes, not keyring.** One generic credential per
   store, named `AOI/dataset-store/<store UUID>`, holds the 32 key bytes and is saved with CRED_PERSIST_LOCAL_MACHINE,
   so it never roams with a profile. The code is about 60 lines over advapi32's CredWriteW, CredReadW, CredDeleteW and
   CredFree, in one module that REQ-SET-010's license key and Stage 4's MES token reuse. DPAPI protects the credential
   under the Windows account the app runs as: every app user of that account can open the store (the app's roles
   decide what each may do), and another Windows account cannot. On Linux, which runs only CI and development, an
   in-memory key store stands behind the same three calls; the Windows CI runner tests the real one. No key goes into
   the workspace, a log or an export.
4. **File format 1.** A 34-byte header (the magic `AOIE`, format 1, algorithm 1 for AES-256-GCM, the store's 16-byte
   key id and a 96-bit nonce from `os.urandom`), then the ciphertext and the 16-byte tag: 50 bytes over the plain file.
   The associated data is the header, the store UUID and the file's workspace-relative path as the rows store it, so a
   file swapped with another, moved, or put into another customer's store fails to open. A store's few thousand writes
   stay far below GCM's limit of 2^32 random nonces per key (NIST SP 800-38D). No key rotation in Stage 1; the key id
   and the format number let a later release re-encrypt.
5. **Files keep their paths; only their bytes change.** A store's files stay at `images/<board model>/<label>/<name>`
   and `datasets/<name>/manifest.json`, so the append-only rows of ADR 0009 stay true. The plaintext SHA-256 stays each
   file's identity (the import's duplicate check, the manifest, the validation lock, a result's golden board hash). No
   ciphertext hash is stored: the GCM tag already proves the ciphertext under the key, and re-encrypting changes it. An
   import writes its workspace copy encrypted from the start and never touches the source. A workspace from before S38
   is moved in by an Admin, file by file: encrypt, write, decrypt and compare the SHA-256, then replace the plain file.
   The image comes back bit for bit, which we read as meeting "Originals are never modified".
6. **Decryption happens only in memory.** `imaging._read_image` takes its bytes from the store instead of `read_bytes`,
   decrypts them, then runs today's checks and `cv2.imdecode`; nothing writes a plaintext temporary file. A store's
   file without the header, or failing its tag, is refused with an AoiError, so a plain file never passes as encrypted.
   `verify_dataset` decrypts each file (the tag checks the ciphertext) and compares the plaintext SHA-256 with its row;
   a missing or wrong key is AOI-TRN-025. A training run refuses a file whose key id is not its store's, with the same
   code. An import reads its encrypted copy back through the store to compare the SHA-256, as it does the plain copy
   today.
7. **Recovery.** The key is lost with the Windows account or its profile, with a local account's password reset by an
   administrator (DPAPI), and with a new PC or a reinstall. When an Admin creates a store, the app prints a recovery
   sheet: the key as 52 base32 characters in groups of four, the store UUID and the key id. Whoever holds the data under
   the contract keeps it: the customer's Admin for a store on their station, Jay's company in its safe for a store on
   our laptops; we keep no copy of a key the customer holds. An Admin types the sheet into Settings on a new PC or
   account, and a check value in the store row (an HMAC-SHA-256 of a fixed text) confirms it; both actions are audited.
8. **Backup.** A workspace backup (Hardening extras, SHOULD) copies the encrypted files as they are and holds no key: it
   restores as is on the same Windows account, and elsewhere with the recovery sheet, which is kept apart from it.
9. **End of an engagement: crypto-shredding.** An Admin action deletes the credential first, records it (an audit entry
   and a row of an append-only `store_shreds` table: store, key id, time, user, file counts), then deletes the store's
   files and its board models' AI models and golden boards. The sheet's holder destroys the sheet, and the written
   confirmation the Legal standard asks for names the store, the key id and the time. With key and sheet gone, a block
   left on an SSD or a file in an old backup cannot be read. Label and box rows are append-only (ADR 0009) and not
   encrypted, so a workspace on our laptops holds one customer, and the engagement ends by deleting it after the shred.
10. **Pins and licenses for S38** (checked 2026-10-09): cryptography 50.0.2 (Apache-2.0 OR BSD-3-Clause), whose
    Windows and Linux wheels bundle OpenSSL 4.0.3 (Apache-2.0) and list 39 Rust crates, each under MIT, Apache-2.0 or
    BSD-3-Clause or a choice including one, save two used only to build (inferred): unicode-ident adds Unicode-3.0, and
    target-lexicon is Apache-2.0 WITH LLVM-exception. At run time it needs cffi 2.1.1 (MIT-0) and pycparser 3.1
    (BSD-3-Clause). MIT-0, MIT without the notice duty, is not on the allowed list: it is the exception ADR 0002 raised
    for argon2-cffi, pending J8, so S38 adds `exception:MIT-0` with that note.
11. **What S38 builds.** Migrations for `dataset_stores` (UUID, customer, key id, check value, who, when), a board
    model's store and `store_shreds`; `aoi/core/crypto.py` (format 1, no Qt) and the key store module; the read and
    import paths of decisions 5 and 6; the Admin move-in, resumable and audited; store creation, the sheet's printing
    and restore, and the shred, each sketched first; tests for the round trip, a changed byte, a moved or swapped file,
    another store's file, a missing key, no plaintext file while training, and Credential Manager on the Windows runner.

## Alternatives considered

- **(a) BitLocker only.** It protects a disk that is off or stolen, nothing more: on a running station every process
  reads the files, and every copy (a backup on USB or a share, a folder copied off a laptop) is plaintext. One volume
  key serves every customer, so there is no store per customer and no shredding one; on a customer's station their IT
  owns it, and the app, a standard user, cannot turn it on. It stays as the baseline (decision 1).
- **(c) An encrypted container per customer** (a BitLocker-protected VHDX, or VeraCrypt). Mounting a VHDX needs
  administrator rights the app does not have; once mounted it is plaintext to every process; Linux CI cannot test it;
  copying a mounted container is no reliable backup. VeraCrypt needs its own kernel driver, and its TrueCrypt License
  3.0 parts are not on the allowed list.
- **(b) with keyring 25.7.0 (MIT)**, as the plan named it. On Windows with Python 3.11 it adds pywin32-ctypes 0.2.3
  (BSD-3-Clause), importlib_metadata 9.0.1 (Apache-2.0), jaraco.classes 3.4.0, jaraco.functools 4.6.0, jaraco.context
  6.1.2, more-itertools 11.1.0, zipp 4.1.1 and backports.tarfile 1.2.0 (all MIT): nine packages for three calls. Its
  Windows backend saves with CRED_PERSIST_ENTERPRISE, which roams with a roaming profile; it picks its backend at run
  time from installed entry points, the PYTHON_KEYRING_BACKEND variable and a `keyringrc.cfg` file, so a station's
  environment can send the key elsewhere; its Linux backend needs a D-Bus secret service CI runners lack.
- **(b) with Windows CNG through ctypes**, for no new dependency, as Q40 hoped. BCryptEncrypt in GCM mode spares three
  packages, but we would write and audit our own binding of a cipher (structures, nonce and tag handling, where a
  mistake is silent), and CNG does not exist on Linux, so CI there could not run the format's tests without a second
  implementation. A crypto binding of our own costs more to trust than three permissive packages.
- **pycryptodome** (no cffi): its own AES code, with fewer reviewers than OpenSSL's, and public-domain parts.
- **EFS on the workspace.** Transparent to every process of the Windows account, one certificate per account rather
  than per customer, and lost with the account unless the customer's IT set up a recovery agent.
- **A per-station key wrapping per-customer keys kept in the database.** One credential, but the wrapped keys sit in
  every backup of the workspace, so removing a customer's row shreds nothing, and one sheet opens every store.
- **A recovery file, or the key wrapped to a public key of Jay's company.** A file is a plain key that ends up beside
  the backups; a company key would open every customer's data, against "Data on a station belongs to the customer".

## Consequences

- **Training speed.** Measured on 2026-10-09 on a cloud virtual machine, not the reference PC (still open in the
  Charter): Intel Xeon Processor at 2.10 GHz, 4 virtual CPUs with AES-NI, 16 GB RAM, Ubuntu 24.04, Python 3.11.15,
  cryptography 50.0.2 with OpenSSL 4.0.3, opencv-python-headless 5.0.0.93. One synthetic board-like PNG of 2592 × 1944
  pixels (5.04 MP, 8,683,001 bytes), 200 times in memory, two runs: encrypting took 3.0 to 3.1 ms per file (0.60 to
  0.63 s for 200), decrypting 2.6 to 2.7 ms (0.54 s), and `cv2.imdecode` of the same PNG 118.5 to 118.8 ms (23.8 s), so
  decryption adds 2.2 % to decoding. Then 200 different boards (8.65 to 8.72 MB each, 1.74 GB in all), each made,
  encrypted, decrypted and decoded once: encrypting took a median 2.8 ms (0.63 s for the 200), decrypting 2.7 ms
  (0.61 s) and decoding 119.6 ms (24.0 s), so decryption adds 2.6 % over the 200 files. From disk (page cache warm,
  four passes), 20 different boards of 8.66 to 8.71 MB took 2.45 to 2.59 s to read, decrypt and decode against 2.41 to
  2.53 s to read and decode, 0.5 % to 2.9 % more. Over 200 such files a run gains about 0.6 s; `verify_dataset` adds
  2.6 to 2.7 ms a file to its 6.5 to 6.6 ms of SHA-256.
- **Three new runtime packages** to pin, lock, audit and list in `THIRD_PARTY_NOTICES.txt` with their license texts; a
  security release of cryptography or its OpenSSL is a pin change under the Security rule's fix deadlines.
- **What the store does not cover.** `aoi.sqlite` (names, labels and boxes; no pixels), the golden boards and AI models
  derived from the images, inspection images under `results/` and the folders an import read from stay plain on disk,
  under BitLocker on our laptops; whether they join the store is left to a later requirement. Nothing guards the files
  from a program or person working as the same Windows account while the app can open the store, or from a Windows
  administrator (as in ADR 0002); plaintext lives in the process's memory and may reach the page file.
- **A board model needs its store at its first import**, before the Freeze sheet asks for a customer today, so S38
  updates the sketches first. A store's file keeps its `.png` name but opens only in the app; the manual says so.
- **A lost credential and a lost sheet lose the store**, as a shred does. The sketch's Q40 now points here.

## As built in S38

- **A board model joins its store when an Admin moves it in, not at its first import** (decision 1 and the fourth
  consequence). With no screen yet to pick a store at an import, a board model in no store keeps its files plain, as
  every workspace from before S38 does, and the freeze refuses it (AOI-TRN-027), as it refuses one in another
  customer's store than the version names. So no frozen version, and from S39 no run that trains on one, holds a plain
  file or a second customer's; our own and synthetic boards get a store of their own before they are frozen. Picking
  the store at a board model's first import stays in the sketch.
- **No screen yet** (decision 11): creating a store, printing its sheet, restoring a key, moving a board model in and
  shredding are `AppContext` calls, Admin only and audited; `docs/sketches/training-datasets.md` proposes their
  screens. The Datasets stage (3 of 4) built them as Settings › Dataset stores.
- **A shred deletes the key from the station it runs on.** A station that restored the key from the sheet holds it
  until that station's workspace shreds the store too, so the written confirmation of decision 9 follows the shred on
  every station that holds the store.
- **A board model's name must name one folder to be moved in** (AOI-TRN-019): a name from before names were checked
  (#112), such as ".", would make its folder all of images/.

