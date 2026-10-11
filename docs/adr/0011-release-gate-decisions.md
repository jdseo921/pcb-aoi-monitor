# ADR 0011: The open release-gate decisions for 0.3.0, taken by industry norm

- Status: Proposed. Jay's merge of this record accepts it. Jay delegated these decisions on 2026-10-11 ("make
  decisions that are the best for industry norm standards"), so this record takes one option for each.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: `docs/release-gate/0.3.0.md` ("What Jay decides before 0.3.0 leaves the building"), issue #73 (S59),
  `docs/security/threat-model.md` (decisions 5 and 6, J6 and J8), [ADR 0007](0007-windows-build.md),
  `docs/tests/station-checks.md`

## Context

The 0.3.0 release gate lists five decisions for Jay. Each one either names a person or a machine, or buys something,
or accepts a gap. A record cannot buy a certificate or name a person; it can fix the rule each one follows, so the
work that remains is an action, not a decision. Decision 3 of the gate (#150, #151, #152) is already taken and built
(Q53, Q58, Q57; merged in #378), so it is not repeated here.

## Decisions

### 1. The reference PC is a declared configuration, not a named machine (gate boxes 2, 3, 5)

Industry practice ties performance budgets to a stated minimum supported configuration, published with the product,
so any machine that meets it can run the checks and a customer can buy to it.

| Part | Reference configuration |
|---|---|
| OS | Windows 11 Pro 64-bit, 23H2 or later, standard user account |
| CPU | Intel Core i5-12500 or AMD Ryzen 5 7600, or faster (6 performance cores) |
| Memory | 16 GB |
| Storage | 512 GB NVMe SSD, workspace on the same drive |
| GPU | none required: the budgets are met on the CPU; a CUDA GPU is optional and only speeds up training |
| Display | 1920 × 1080 at 100 % scaling; also checked at 1366 × 768 (#104) |

The station checks (`docs/tests/station-checks.md`) are run by the release engineer of the build, today Jay, on a
machine that meets the table, and the results are kept under `docs/tests/` with the machine's exact parts. A slower
customer station is a known risk to note, not a failed gate.

### 2. Code signing: an OV certificate held in a CA's cloud signing service, timestamped (J6, gate box 5)

Since June 2023 the CA/Browser Forum requires code-signing keys to live in certified hardware, so a key in a file on a
build machine is no longer an option, and since March 2026 a certificate lasts at most 460 days. Azure Artifact
Signing was considered first and set aside: it issues public certificates to individual developers only in the USA and
Canada, and to organisations with a verifiable history, which Jay, in Australia and not yet trading as a company, is
not. SignPath Foundation's free signing is for open-source projects only, which this one is not. So:

- **Stage 1 pilot (now, free):** the installer and executables are signed in CI with a certificate from our own
  private code-signing CA, and the customer's IT trusts that CA on the pilot stations only (Group Policy or `certlm`,
  "Trusted Publishers" and "Trusted Root"). This is the usual practice for internal line-of-business software. The
  private key stays offline with Jay; CI receives a short-lived signing certificate per release. `SHA256SUMS.txt` keeps
  shipping beside the installer. The build still says it is not publicly signed.
- **Before any second customer or public download:** buy an Individual or Organisation Validation (OV) code-signing
  certificate from a public CA that offers cloud signing usable from GitHub Actions (for example Certum's cloud OV,
  SSL.com eSigner or Sectigo with a cloud key; about US$120 to US$320 a year), and sign every `.exe`, `.dll` and the
  installer with Authenticode, SHA-256, with an RFC 3161 timestamp. EV is not needed: since 2024 Windows SmartScreen
  gives EV no head start, and reputation builds per certificate with either.
- If Jay later registers a company with a verifiable history, Azure Artifact Signing becomes the cheaper option and
  replaces the bought certificate at its renewal.

The actions left are Jay's: create the private CA key offline for the pilot, and later buy the OV certificate.

### 3. Two-person release approval: a written exception with compensating controls, until a second engineer (J8)

A one-person team cannot have two approvers. The accepted practice (OpenSSF Scorecard and SLSA treat it the same way)
is a written, time-limited exception backed by controls that a second reviewer would otherwise provide:

- `main` is protected: changes come by pull request, the CI checks "Tests (ubuntu-latest)", "Tests (windows-latest)",
  "Lint and format", "Type check", "Security scans" and "Lock files match their inputs" are required, and force
  pushes and deletion are refused. Auto-merge then waits for them.
- Every pull request gets an automated review before merge (the AI review used on this repository), recorded on the
  pull request.
- A release is built only by CI from a tag, with `SHA256SUMS.txt` and the SBOM, and is signed (decision 2).
- The exception ends when a second engineer joins, or at 1.0, whichever is first.

Turning on the branch protection is a repository setting for Jay to switch on (one command, in the release gate).

### 4. Korean: Stage 1 ships in English; Korean waits for a professional review (gate box 7)

Shipping a translation nobody qualified has read is against localisation practice (ISO 17100 asks for a second
linguist's revision). The UI loads no Korean translation before the 2H 2027 localisation anyway (REQ-SET-005), so:

- Gate box 7 is judged on the English screens for 0.3.0: the 39 approved screenshots, every role and both themes.
- Korean text in the release notes, manuals and demo scripts stays marked "draft, needs native review" and is not
  given to a customer as final.
- Before the localisation ships, a professional translator with SMT/AOI terms revises the UI and the documents, and
  box 7 is closed on Korean screenshots.

### 5. Upgrade and rollback: rehearse on a production-like workspace now, repeat on the first customer's copy (box 4)

Upgrades are tested on data shaped like production when production data is not yet available, and again on a copy of
real data as soon as it exists:

- Now: build a workspace with the previous build from the public DeepPCB boards on the engineering laptop (the photos
  never leave it), upgrade it with 0.3.0, check every record, image and AI model opens, then follow "Going back to an
  earlier build" in `docs/install/install.md` and check the earlier build opens its backup. The result is recorded
  under `docs/tests/`.
- Later: the same steps on a copy of the first customer's workspace, before that customer's station is upgraded.

## Consequences

- The release gate lists actions with an owner instead of open questions: set up pilot signing, switch on branch
  protection, run the station checks on a machine meeting decision 1, and rehearse the upgrade (decision 5).
- 0.3.0 can be released to a Stage 1 customer once boxes 2, 3, 5 and 6 pass on a signed build; Korean is out of scope
  for that release by decision 4.
