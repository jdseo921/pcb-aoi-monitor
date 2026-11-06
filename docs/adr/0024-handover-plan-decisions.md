# ADR 0024: Decisions of the handover plan (D1 to D25)

- Status: **Proposed. Every decision below is provisional** until Jay confirms or changes it; a confirmed decision
  loses the word "provisional" in the PR that records the confirmation, and a changed one is rewritten with Jay's
  reason. Drafted 2026-10-31 under Jay's instruction (thread "Handover plan: diagnosis and plan of record"): "The
  handover plan is the plan of record from now on. Its decisions D1 to D19 are mine to take; where it names a
  recommended default, treat the default as my provisional answer and mark it 'provisional' until I confirm."
- Source: `docs/plans/2026-11-handover-plan.md` section 3 (D1 to D19). Where the production plan
  (`docs/plans/2026-11-production-plan.md` section 3) words D1, D3 or D7 differently, the handover plan's wording is
  used and the difference is noted. D20 to D22 are new: MUST conflicts with the [Engineering standard](../standards/engineering.md) found by the
  diagnosis (`docs/reviews/2026-11-diagnosis.md`, section 1.8), which CLAUDE.md rule 2 says need Jay's explicit approval
  before any code relies on them. D23 settles the name G1.
- Rows: priorities that wait on a decision carry it in brackets in `docs/requirements/stage1.md`, for example
  `MUST G1 (provisional: ADR 0024 D3; gated once built)`; the convention is in `docs/requirements/README.md`.

## Context

The production-readiness review of 2026-11-01 found a well-built Stage 1 tool that cannot yet run unattended in a
factory. The handover plan turns that into gates G0 to G6 and nineteen decisions to take at G0. The decisions bind
what is built, in what order, and what the company and the factory are told; the [Charter](../standards/charter.md) ("Who decides") makes them
the product owner's.

## Decisions

| # | Decision | Recommended default (provisional) | Requirement rows it touches | Note |
|---|---|---|---|---|
| D1 | Evidence policy per inspected board | NG and WARN: full-resolution overlay and both maps, kept for the retention the factory names (default 2 years). OK: JPEG overlay at quality 90 plus a preview at `PREVIEW_PX`, maps 7 days. The factory may require full resolution for every board; then the station gets the disks for it. **Confirmed by Jay, 2026-11-01**, as written (decision card in the Stage 1 thread). The OK board's files are built in PR 1.2 (`Settings.ok_evidence`: `jpeg`, or `full` for a factory that requires full resolution); the 2-year retention of NG and WARN evidence is not built yet (REQ-LOG-010) | REQ-INSP-012, REQ-LOG-006, REQ-LOG-010, REQ-INSP-008 | The production plan said "forever" for NG and WARN; the handover plan's 2 years is used. **Gap:** says nothing about the original images that REQ-INSP-020 moves to `done/` (4.7 MB per 5 MP board measured, as much again as everything else); see "Changes Claude recommends" |
| D2 | Feature freeze until `v0.5.0` | Yes, with the handover items in the plan as the only exceptions. **provisional** | REQ-SET-023 (the version discipline that makes the freeze visible); every row: no new feature row | |
| D3 | Accounts with passwords | Before G1, not optional: the audit trail of a quality instrument names people. **Confirmed by Jay, 2026-11-02**, as written (decision card in the Stage 1 thread). Built in PRs D.1 to D.3 | REQ-USR-002, -003, -004, -005, -006 | The production plan deferred it to Stage 3 or 4; the handover plan moves it into G1 |
| D4 | What the dataset-store encryption is for | Keep it as the vendor-laptop control; BitLocker is the station's disk control; ADR 0010 says so. **provisional** | REQ-TRN-017 | |
| D5 | IPC wording for Stage 4 | Amend REQ-SET-003 when Stage 4 starts, to "listens on no TCP or UDP port; a local named pipe between the app's own processes is allowed". **provisional** | REQ-SET-003 | |
| D6 | Trace gate scope | The pull-request title must cite a requirement or an issue; individual commits need not. **provisional** | none (tooling, PR 2.5) | |
| D7 | Korean | Operator-facing screens, alarms and the errors an Operator can see: before G1. Engineer and Admin screens: before G3 if the company's engineers are Korean, else with Stage 3. **provisional** | REQ-SET-006 (operator scope, G1), REQ-SET-028 (the rest, G3) | The production plan said "after Stage 3, nothing before"; the handover plan is used. REQ-SET-006 was split into two rows for this |
| D8 | Reference PC | Bought or borrowed before `v0.4.0` is tagged; the station checks of `docs/tests/station-checks.md` are its exit criterion. **provisional** | REQ-INSP-007, REQ-INSP-011, REQ-INSP-008 (power-off tests) | Without it no performance budget and no soak result can be claimed (diagnosis 1.2) |
| D9 | How images reach the station | (a) A watched input folder fed by the factory's existing imaging station, with a file-naming contract (board ID, view, time). (b) Stage 2 cameras integrated by the company; (c) an operator loads folders by hand, which does not replace anyone. Default: (a) now, (b) as the company's Stage 2 project. **Confirmed by Jay, 2026-11-03**, as written (decision card in the Stage 1 thread) | REQ-INSP-020 | The naming contract itself is still to be agreed with the factory |
| D10 | How results leave the station | A result file per board in an output folder (JSON and a one-line CSV: board ID, verdict, time, model version, recipe revision, defect list) within 1 s of the verdict, plus the end-of-shift CSV. PLC or light tower in Stage 3; MES in Stage 4. **Confirmed by Jay, 2026-11-03**, as written (decision card in the Stage 1 thread) | REQ-INSP-021, REQ-LOG-002 | |
| D11 | Who looks at WARN, and what happens to NG | A review station with the Review function (Real defect, False call); NG boards go to the factory's rework flow with the overlay printed or shown. **provisional** | REQ-INSP-013, REQ-LOG-009 | |
| D12 | Acceptance targets | Per defect type, as counts: missed-defect rate at most X % with an upper 95 % bound at most Y %, false-call rate at most Z %, on at least N locked boards; the factory names X, Y, Z and N. Without numbers signed at G0, G2 cannot be passed or failed. **provisional** | REQ-TST-008, REQ-INSP-014, REQ-TRN-019 | Claude recommends opening with the [Customers & Launch](../standards/customers-and-launch.md) proposal (no missed Critical defect, false calls 5 % or less, 1 s or less per image) |
| D13 | Shadow period | Four weeks or 2,000 boards, whichever is later; exit when escapes are under the G0 target with its bound and false calls are under target after tuning. **provisional** | REQ-TST-009 | |
| D14 | Sampled audit rate | One OK board in 50 to a person at G5, one in 200 at G6, adjusted by the drift monitor. **provisional** | REQ-TST-010, REQ-INSP-019 | |
| D15 | What the company receives | Signed binaries, the release kit, documentation, training and a support contract; source in escrow. If source is handed over, production plan Stages 2 and 3 become gates for the handover. **provisional** | REQ-SET-027, REQ-SET-012 | [Legal & Compliance](../standards/legal-and-compliance.md): escrow SHOULD be offered |
| D16 | Licence and term | REQ-SET-010 (offline licence key bound to the station) and REQ-SET-022 (EULA in the installer) before G3; perpetual per station plus maintenance, or subscription, per the Charter's open business decision. **provisional** | REQ-SET-010, REQ-SET-022 | The plan's G1 table builds both in G1 (train F); the rows are moved to G1 accordingly |
| D17 | Who owns the trained AI model and the factory's images | Licensed to the factory for their own boards; images stay on their station; the Legal & Compliance clause; written into the G0 document. **provisional** | REQ-TRN-017 | Legal & Compliance proposes the same default |
| D18 | Support model | The company is first line with the support bundle and the runbook; Jay is second line; response times named; what the company may change (thresholds, recipes, users) and may not (model files, migrations). **provisional** | REQ-LOG-007, REQ-SET-011, REQ-SET-024, REQ-SET-025, REQ-SET-026 | |
| D19 | Minimum defect size and the defect list | The factory names the smallest defect the program must find, in millimetres, per defect type from the mandatory set; camera resolution and AI input size follow from it. **provisional** | REQ-INSP-014, REQ-TRN-016 | |
| D20 | **Deletion without an Admin action (MUST conflict)** | Engineering, "Disk and retention (MUST)": "nothing is deleted without an Admin action". Proposed: an Admin confirming the station's retention policy (D1) on Settings, audited, is the Admin action that every later sweep acts under; the sweep audits each run with counts. Applies also to the OK-map sweep already shipped. **provisional, needs Jay's explicit approval**. PR 1.3 builds it as proposed (Settings › Confirm Retention Policy, `retention.confirm`) for every step but the OK-map sweep, which still runs unconfirmed as shipped | REQ-LOG-010, REQ-LOG-006, REQ-INSP-012 | Without this decision REQ-LOG-010 and the 95 % disk rule cannot be built inside the Standard |
| D21 | **Log retention (MUST conflict)** | Engineering: "Logs archive after 30 days (GUI §4.4)". The production plan says 90 days, gzip after 7. Proposed: compress after 7 days, archive (move to `logs/archive/`) after 30, delete after 90 under D20's Admin-confirmed policy. **provisional, needs Jay's explicit approval** | REQ-LOG-010, REQ-LOG-003 | |
| D22 | **Release approval and signing-key custody (MUST conflict)** | Engineering, "Signing (MUST)": release builds "after two people approve", the key "in a hardware token or cloud signing service". Proposed: until a second engineer joins, a fresh-eyes reviewer agent's written review plus Jay's approval stands in for the second person on each release (as the Charter already allows for code review), recorded in the release-gate file; the pilot CA key moves to a hardware token or a cloud signing service before the first factory station is signed, or Jay records why not. **provisional, needs Jay's explicit approval** | REQ-SET-012, REQ-SET-027 | |
| D23 | **The name G1** | The Charter's G1 (customer validation report) is the handover plan's G2; the plan's G1 is "safe to run". Proposed: the register's release names follow the plan of record (G1 = `v0.4.0` safe to run; G2 = validation; G3 = handover), the Charter's gate table is updated by Jay, and the 71 existing MUST G1 rows keep their priority (they must all hold at `v0.4.0` anyway). **provisional** | every MUST G1 row; `docs/requirements/README.md` | Nothing changes in CI: the gate still reads `MUST G1` |
| D24 | **No account can be claimed at a station (usability sweep H1)** | Industry norm: no default or unclaimed privileged account goes into service (IEC 62443-4-2 CR 1.5, "change default authenticators at installation"; OWASP ASVS V2, no default credentials; NIST SP 800-63B). (a) Until an Admin has a password, only the Admin account may choose one: the station's first Admin. An Engineer's password is chosen only with an Admin who has one signed in (hand-over, REQ-USR-006), never by whoever picks the name first. (b) Outside the demo, no board model is made at a station whose Admin has no password: the first-run guide's first step is the Admin's password, its Create and the header's + New stay off until it is chosen and say so. The service keeps accepting a board model made by code (tests, `tools/seed_workspace.py`); the screen is the gate. **Confirmed by Jay, 2026-11-06** ("Set H1 and H2 rules using industry norms", usability sweep thread) | REQ-USR-005, REQ-USR-006, REQ-SET-013 | Before, the guide offered the Admin's password beside step 1, and an Operator could choose the Engineer's or the Admin's password on a station where no Admin had one (verified 2026-11-06) |
| D25 | **Each role lands on its own work (usability sweep H2)** | Industry norm: role-based displays, the operator's run screen first (ISA-101.01 HMI display hierarchy; AOI vendors' operator mode opens on the production screen). (a) A start or sign-in as an Operator opens Inspection, not the page last shown or Home; an Engineer or Admin keeps REQ-LOG-005's page last shown. (b) An Operator's Home keeps its six cards, each greyed with the role it needs (REQ-USR-001, unchanged), and leaves out What is missing: a set-up checklist for Engineers and Admins, not a control an Operator could use. A2's "greyed, never hidden" keeps holding for every control. **Confirmed by Jay, 2026-11-06**, as D24 | REQ-USR-001, REQ-LOG-005, REQ-TRN-021 | Before, an Operator's Home showed four greyed cards and the whole What is missing list with every button greyed |

## Changes Claude recommends (for Jay to accept or refuse)

1. **D1: add the originals.** State whether originals moved to `done/` are kept, for how long, and on which disk. With
   them a 5 MP station writes about twice as much per board.
2. **D1: name the station disk.** Measured synthetic sizes put a 1 TB station full on day 14 to 18 at one board every
   10 s; size the disk from D1 and the factory's throughput before G1, not after.
3. **D12: open with the Customers & Launch proposal** rather than blank X, Y, Z, N, so the factory reacts to numbers.
4. **G3's tag:** the plan gives `v0.4.1`, which Stage 2 already takes; proposed `v0.5.1`.
5. **REQ-TST-009 and -010:** the plan marks them MUST G1 but builds them in G4 and G5; proposed priority "MUST G4" and
   "MUST G5" (or keep G1 and pull Prompt 16 forward). This PR registers them as MUST G1 with the provisional bracket.

## Consequences

- Rows that depend on a provisional decision are registered now and listed in the trace matrix as "no test"; the gate
  holds each one from the PR that builds it (bracket removed with its first passing test).
- G1 code does not start until D1, D3, D8, D9, D10 and D20 to D22 are confirmed; the other decisions block later gates
  only.
- Each later change to a decision is a docs PR that rewrites its row here with Jay's reason
  (`docs/plans/claude-code-prompts-handover.md`, utility prompt "A decision confirmed or changed outside a prompt").
