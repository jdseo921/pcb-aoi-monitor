# ADR 0020: Trial dataset versions, frozen by one person

- Status: Proposed under Jay's instruction of 2026-10-13 06:06 UTC, item B1 of the business-readiness brief (decision
  D1, findings F1 and F2): "one user can freeze, split and lock a dataset version and train from it with no
  second-user label check and no agreement check. Such a version and every AI model from it is marked Trial everywhere
  its name appears … The Validated path keeps today's checks and marks the version Validated. The customer validation
  report and the go-live gate refuse a Trial version with a plain message and the button that starts the checks. The
  validation set minimums do not change." Jay's merge of this record accepts it.
- Date: 2026-10-13
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-004, REQ-TRN-005, REQ-TRN-006, REQ-TRN-012, REQ-TRN-016, REQ-TST-008, ADR 0009 (labels, checks and
  dataset versions), ADR 0018 (first AI model goes live), Jay's ADR "Stage 1 for one person" (see below), migration
  0027, AOI-TRN-052 and AOI-TST-009 (new)

**Numbering.** Jay's message names the decision record `docs/adr/0014-stage1-for-one-person.md`, with the brief
(`docs/plans/2026-10-business-readiness-brief.md`). Neither is in the repository, and the repository's ADR 0014 is the
master samples record (`0014-master-samples-each-shift.md`), so that file takes another number when it is pushed. This
record is 0020, the next free number here; it says how B1 is built. Where Jay's record decides otherwise, Jay's record
wins and this one is changed to match.

## Context

ADR 0009 made every dataset version wait for a second user: every NG label and 10 % of the OK labels checked by
someone other than the labeller (REQ-TRN-004), and a labeller agreement check of two people on 100 images that reached
its targets (REQ-TRN-016). Both are MUSTs, both protect a customer's validation, and both need two people. A company of
one person, as the business starts, could therefore never freeze a version, never train, and never show a customer an
AI model of the customer's own boards (F1, F2).

## Decision

1. **A version is Validated or Trial.** Migration 0027 adds `datasets.assurance`, Validated or Trial, which never
   changes, as the rest of the row. Every version frozen before it is Validated: it was frozen with the checks.
2. **A Trial version needs no second person.** `freeze_dataset(trial=True)`, and on screen the Freeze sheet's
   **Trial: one person, no checks**, freezes a version with no label check and no agreement check; it names no agreement
   check (`agreement_check_uuid` empty, the manifest's `agreement_check` null). Every other refusal holds: the store
   and its customer, the view, the name, a version of that name, no image. The same person splits and locks it and
   trains from it; the validation set keeps its minimums (50 OK images, 30 % of the NG), and so does training (20 OK).
   The Freeze sheet opens on Validated each time, so Trial is chosen, never carried over.
3. **Trial is said wherever a Trial version or its AI model is named.** A version's name keeps REQ-TRN-005's format
   (DS-TBOXA1-R3-TOP-v4); the Versions table's new Checks column says Validated or Trial, and the Dataset version list
   adds "(Trial)". An AI model trained from a Trial version is named `v1.0 (Trial)`: that name is its registry row's,
   so it is what the AI models list, Inspection's model line, Home, the audit entries and the card's title show, and
   what a record's and the CSV's `model_version` would name, though under decision 4 it judges no board; its files
   are `v1.0-trial`. It takes the next number, as any version does (a Trial v1.0 and
   a Validated v1.0 never both exist). Its card's first line starts with a plain sentence: "Trial: one person froze
   <version> without a second person checking its labels or an agreement check, so this AI model cannot go live or
   back a customer validation report", and its known limits add that a wrong label may have taught it. The
   `dataset.freeze` and `model.train` entries carry `assurance`.
4. **The go-live gate refuses a Trial AI model,** first or later (AOI-TRN-052, in `_switch_to`). A board model's
   first AI model, which goes live when trained (ADR 0018), stays inactive when it is a Trial one, and Training says
   so. Inspection names a Trial AI model that waits as a Trial, with Start the Checks in place of Activate, and offers
   a Validated version that waits before a Trial one. Home, AI Model Test, Compare and Training say a Trial AI model
   does not go live and point to the checks, never to Activate. Since no AI model was live before it, the first AI
   model trained from a Validated version after Trial ones goes live as a board model's first does (ADR 0018). Both
   refusals are a step taken as approved, so they show as information with Start the Checks, logged as information
   and stored as no ERROR alarm. This is the recommended option of the card put to Jay on
   2026-10-13 06:15 UTC ("Never live"), not yet answered when this was written: Jay's message says the gate refuses a
   Trial version, and allowing a Trial AI model live later is one check removed, while taking back verdicts a Trial AI
   model already made is not possible. The other options were "Live, marked Trial" (only the report refuses) and "Live
   until Validated".
5. **The customer validation report refuses Trial,** for a run on a Trial version's locked validation set or of an AI
   model trained from one (AOI-TST-009). The run, its CSV and AI Model Test's own report stay.
6. **Start the Checks.** Both refusals' dialogs have a Start the Checks button beside OK, for a role that can open
   Training: it opens Training on the board model, on the Samples tab with Show › Unchecked while a label still waits
   for its check, else on the Datasets tab, whose labeller agreement runs the agreement check. Then the user freezes a
   Validated version and trains from it.
7. **The demo stays Validated.** The demo bundle's version is built by `tools/trainable.py`, which makes a Validated
   version unless asked for a Trial one, so the 45-minute script's Activate Selected still activates it.

## Consequences

- **A departure from two MUSTs, approved.** REQ-TRN-004 and REQ-TRN-016 now hold for Validated versions only. Jay
  approved it in the message quoted above, citing the brief and Jay's ADR "Stage 1 for one person" as the approval. The
  register's rows say so; the Engineering standard's text about the checks needs the same exception, which this change
  does not edit.
- **No verdict changes.** A Trial AI model never goes live, so it judges no board, and the Validated path is as
  before. The synthetic regression set runs with no AI model; its `expected.json` is unchanged. No customer notice is
  needed.
- **A Trial AI model cannot be tested on AI Model Test,** which tests the active AI model. One person can still train
  it and read its card and its training's figures; testing it waits for Validated, or for Jay to choose another
  option of decision 4.
- **Upgrade.** Migration 0027 marks every version frozen before it Validated. A version's row never changes, so a
  Trial version never becomes Validated: the checks are made on the samples, and a new version is frozen.
- Not done: a check that a Trial version's AI model left the workspace only as a Trial one (an exported `.pt` keeps
  `assurance` in its metadata, which no import reads yet).
