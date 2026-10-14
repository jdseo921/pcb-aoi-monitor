# ADR 0020: Trial dataset versions, frozen by one person

- Status: Proposed under Jay's instruction of 2026-10-13 06:06 UTC, item B1 of the business-readiness brief (decision
  D1, findings F1 and F2): "one user can freeze, split and lock a dataset version and train from it with no
  second-user label check and no agreement check. Such a version and every AI model from it is marked Trial everywhere
  its name appears … The Validated path keeps today's checks and marks the version Validated. The customer validation
  report and the go-live gate refuse a Trial version with a plain message and the button that starts the checks. The
  validation set minimums do not change." Jay's merge of this record accepts it. Decision 4 changed on Jay's answer of
  2026-10-14 00:03 UTC to Q63 of the first-run guide sketch ("Live until Validated"; B5).
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
   adds "(Trial)". An AI model trained from a Trial version is named `v1.0 (Trial)`: that name is its registry row's, so
   it is what the AI models list, Inspection's model line, Home, the audit entries and the card's title show, and what a
   record's and the CSV's `model_version` name for a board it judged (decision 4); its files are `v1.0-trial`. It takes
   the next number, as any version does (a Trial v1.0 and a Validated v1.0 never both exist). Its card's first line
   starts with a plain sentence: "Trial: one person froze <version> without a second person checking its labels or an
   agreement check, so this AI model can judge boards only while no Validated AI model of its board model has gone live,
   and cannot back a customer validation report", and its known limits add that a wrong label may have taught it. The
   `dataset.freeze` and `model.train` entries carry `assurance`.
4. **A Trial AI model goes live only while no Validated one has, and never replaces one** ("Live until Validated",
   decided by Jay on 2026-10-14 00:03 UTC, as Q63 of `docs/sketches/first-run-guide.md` recommends). A board model's
   first AI model, a Trial one included, goes live when trained (ADR 0018): one trained with none active and no
   Validated one before it. While no Validated AI model is live, a Trial one is activated and rolled back to as any
   version is, and Inspection, Home, AI Model Test and Compare offer Activate for one that waits, which its name marks
   (Trial); a Validated version that waits is offered before a Trial one. A Validated AI model trained while a Trial one
   is live installs inactive, as every later version does (REQ-TRN-010), and What is missing's Validated list offers to
   activate it. Once a Validated AI model is live (`validated_live`), the go-live gate refuses every Trial AI model,
   activated or rolled back to, with AOI-TRN-052 (in `_switch_to`), so the active one stays Validated; Training greys
   Roll Back when it would go to one, and says so when one is trained. The refusal is a step taken as approved, so it shows as information with Start the
   Checks and is stored as no ERROR alarm. This decision first read "The go-live gate refuses a Trial AI model, first
   or later" ("Never live", recommended on the card of 2026-10-13 06:15 UTC and built that way); the other option,
   "Live, marked Trial" (only the report refuses), was not chosen. That a Validated AI model does not take a live Trial
   one's place by itself is how this is built, not a decision of Jay's: it keeps "a new version installs inactive"
   (REQ-TRN-012) wherever an AI model is live.
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
- **Verdicts change, approved.** A Trial AI model judges boards while no Validated one has gone live: the AI check
  adds NG and WARN calls to the Golden board comparison, and a first AI model's Golden board replaces the one set with
  Set Reference (ADR 0018). It departs from REQ-TRN-012 (a MUST) and from REQ-TRN-004's "never goes live", approved by
  Jay on 2026-10-14 ("Yes to every questions", Q63). Every record of a board it judged names it `v1.0 (Trial)`, and the
  customer validation report still refuses it (decision 5). The synthetic regression set runs with no AI model; its
  `expected.json` is unchanged. The customer notice below is drafted for Jay to send.
- **A Trial AI model is tested on AI Model Test** while it is the active one. Its run and AI Model Test's own report
  stay; the customer validation report refuses it.
- **Upgrade.** Migration 0027 marks every version frozen before it Validated. A version's row never changes, so a
  Trial version never becomes Validated: the checks are made on the samples, and a new version is frozen. A Trial AI
  model trained with a build made before "Live until Validated" (none was released) stays inactive at the upgrade;
  with none active, Inspection, Home and Training offer Activate for it. Its card, written when it was trained, still
  says it cannot go live. An AI model trained before a version had an assurance counts as Validated, those of 0.2.0
  trained from the sample table with no checks included, so a board model with one live takes no Trial AI model.
- Not done: a check that a Trial version's AI model left the workspace only as a Trial one (an exported `.pt` keeps
  `assurance` in its metadata, which no import reads yet).

## Customer notice (draft, for Jay to send)

> **Subject: a Trial AI model now judges boards until a Validated one does**
>
> From the next release, one person can freeze a Trial dataset version, whose labels no second person checked, and
> train an AI model from it. When that is a board model's first AI model, it judges that board model's boards as soon
> as training ends, together with the Golden board comparison, and boards are compared with the Golden board that
> training built. Verdicts of that board model can change from then on: the AI check can add NG and WARN calls, and
> the new Golden board can change what the comparison finds. Your engineer can also activate a later Trial AI model,
> or roll back to one, until a Validated AI model judges that board model's boards.
>
> What does not change: a Trial AI model is named with "(Trial)" on every screen, record, CSV export and audit entry;
> it never replaces a Validated AI model, and once a Validated one judges a board model's boards, no Trial one does
> again; no customer validation report is made from a Trial AI model; nothing changes when you upgrade.
>
> What we ask: treat a Trial AI model's verdicts as not validated. Test it on AI Model Test on its locked validation
> set before you rely on it, and have a second person check the labels and run the agreement check (Start the Checks)
> for a Validated AI model before production. To stop it judging boards, untick "Use the self-trained AI model" in the
> Recipe Editor and save the recipe. Where Shift Check is on, the board model needs a shift check with the new AI model
> before its next board.
