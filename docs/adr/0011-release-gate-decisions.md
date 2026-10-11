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

### 2. Signing: keyless build provenance now, Authenticode when it can be paid for (J6, gate box 5)

Since June 2023 the CA/Browser Forum requires code-signing keys to live in certified hardware, so a key in a file on a
build machine is no longer an option. Every route to an Authenticode signature Windows trusts costs money or an
eligibility Jay does not have today: Azure Artifact Signing needs a paid subscription and, for an individual, a
documented US or Canadian address; a public CA's OV certificate costs about US$120 to US$320 a year; SignPath
Foundation's free signing is for projects under an open-source license, which this repository does not have. So, in
order:

1. **Now, free, nothing to keep or pay for:** every build of `main` and of a tag signs its provenance with GitHub's
   keyless signing (Sigstore, `actions/attest-build-provenance` in `build.yml`): the installer, the app's executable
   and `SHA256SUMS.txt` carry a signed record of the repository, commit and workflow that built them, kept in GitHub
   and the public Sigstore log. Anyone verifies a file with `gh attestation verify FILE -R jdseo921/pcb-aoi-monitor`.
   This is the supply-chain norm SLSA asks for (build level 2) and needs no secret and no person. It is not an
   Authenticode signature: Windows still names the publisher unknown, so builds stay labelled "unsigned, internal".
2. **For the Stage 1 pilot station:** the customer's IT checks the installer's attestation (or its SHA-256 against
   `SHA256SUMS.txt`) before installing, and may allow the app by hash in its application control. This is enough for
   one supervised pilot; it is not enough for a product handed over without us.
3. **Before a second customer or any download outside the pilot:** add an Authenticode signature, SHA-256 with an
   RFC 3161 timestamp, by the first route that becomes open: Azure Artifact Signing (cheapest, once Jay has a paid
   subscription and a documented US address, or a company), else a public CA's OV certificate with cloud signing.
   The workflow step goes in next to the provenance step; the provenance stays.

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

- The release gate lists actions with an owner instead of open questions: an Authenticode route when it can be
  paid for, switch on branch
  protection, run the station checks on a machine meeting decision 1, and rehearse the upgrade (decision 5).
- 0.3.0 can be released to a Stage 1 customer once boxes 2, 3, 5 and 6 pass on a signed build; Korean is out of scope
  for that release by decision 4.
