# ADR 0023: A board model's name is checked where it is entered

- Status: Proposed under Jay's instruction of 2026-10-13 14:22 UTC, item B4 of the business-readiness brief (D4 part,
  finding F9): "a board model name is validated when it is entered, with the same rule freeze applies today
  (AOI-TRN-039), and the message says what a valid name looks like; a Korean-only name is refused at entry, never
  later. Add a test with the names that used to slip through." Jay's merge of this record accepts it.
- Date: 2026-10-13
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-005, REQ-TRN-001, REQ-TRN-017, ADR 0009 (labels, checks and dataset versions), ADR 0021 (the New
  board model dialog), AOI-TRN-054 (new), AOI-TRN-039, AOI-TRN-019, AOI-TRN-005

**Numbering.** ADR 0022 is B3's record, on the pull request this one is stacked on, so this record is 0023. As for
ADR 0020 and 0021, the brief is not in the repository; where it decides otherwise, it wins and this record is changed
to match.

## Context

A dataset version is named DS-<BOARDMODEL>-<REV>-<VIEW>-v<N>, <BOARDMODEL> being the ASCII letters and digits of the
board model's name in upper case (`datasets.token`, ADR 0009, decision 5). A name with none, such as one in Korean
only, gives no <BOARDMODEL>, so `freeze_dataset` refuses it with AOI-TRN-039, a rule ADR 0009 left open for Jay. But
nothing refused such a name earlier: + New board model, a first import and Set Reference took `보드`, `---`, `ＴＢＯＸ`
(full-width Latin letters, as a Korean input method types them in full-width mode), `АБВ` (Cyrillic letters that look
like Latin ones) and the like, and an Engineer found out at Freeze Dataset…, after importing and labelling the board
model's images and getting its labels checked, that none of it could be frozen under that name (F9). The board model
cannot be renamed, so the images had to be imported again under another name.

## Decision

1. **One rule for a new board model's name, applied where the name is entered.**
   `AppContext.board_model_name_refusal(name)` returns the refusal a new board model of that name meets, writing
   nothing, or None: AOI-TRN-019 for a name that cannot name its folders (`one_folder_name`, as before), then
   **AOI-TRN-054 for a name with no Latin letter or digit** (`datasets.token(name) == ""`, the very test freeze makes
   with AOI-TRN-039), then AOI-TRN-005 for a name that differs from an existing one only in case (as before). Every
   call that makes a board model raises it before anything is written (`_refuse_new_name`): `ensure_board_model`, and
   so `create_customer_board_model` before a store or key is made; `import_samples`, whose first import makes one;
   `set_reference`; and a training run, for its version's board model, which the workspace holds and so keeps. The two
   helpers it replaces (`_refuse_unsafe_name`, `_refuse_case_variant`) are gone, so the rule is written in one place.
2. **The message says what a valid name looks like.** AOI-TRN-054 names the name, says it has no Latin letter or digit
   (A to Z, 0 to 9, as an English keyboard types them) and that a board model's dataset versions are named with those,
   and says to give a name with at least one, such as TBOX-A1, other letters, such as Korean ones, being allowed beside
   them, as in "TBOX-A1 메인보드"; nothing was made. "As an English keyboard types them" is there for full-width letters,
   which look like A to Z and are refused.
3. **The New board model dialog checks the name as it is typed**, through the same call, so the rule is not written a
   second time in the screen: while the name (its spaces at the ends dropped, as Create drops them) is one a new board
   model may not have, a muted, word-wrapped line under the name field gives the refusal as the error dialog would,
   its code, what happened and what to do, and Create is off; Enter makes nothing. This covers the case and folder
   rules too, which before were said only after Create. A refusal the name alone does not give (a board model in no
   store named with a customer, AOI-TRN-044; no store where keys live in memory only, AOI-TRN-053; the role) still
   shows Create's dialog.
4. **Enter in the form is the fields' own.** Qt made Cancel the dialog's default button as it opened, Create being off
   with no name typed, so Enter in an empty or refused name field pressed Cancel and closed the form, and Enter on a
   name that Create's dialog then refused closed the form behind that dialog. The dialog now takes Enter in the form
   itself: the name and customer fields give it to Create (`make`), which does nothing for a refused name, and no
   default button is pressed after it. A focused button takes Enter as before.
5. **A name the workspace already holds is kept.** A board model made before this rule under a name it refuses keeps
   its name, imports, takes a reference and inspects as before, and + New with its name, typed exactly, chooses it; only
   freeze refuses it, with AOI-TRN-039, as it did, saying to import its images under a name with a Latin letter or
   digit. AOI-TRN-039 stays for that case. Refusing such workspaces at start-up, or renaming their board models, was
   not chosen: a rename touches folders, AI model files and records, and Jay asked for a check at entry.

## Consequences

- ADR 0009's open rule is decided as built: a board model's name needs a Latin letter or digit, now from its creation.
  Deriving a <BOARDMODEL> from Korean letters (romanised, or a code) was not chosen; Jay's instruction refuses such a
  name.
- `board_model_name_refusal` is a new read on the service API, with no role check (it writes nothing), classified as
  such in `tests/test_roles_and_audit.py`. `ensure_board_model`, `import_samples`, `set_reference` and
  `create_customer_board_model` refuse names they took before; no caller in the app or its tools makes a board model of
  such a name (the demo, the render workspace, the soak run and the seeded workspace use Latin names).
- Nothing is migrated and no verdict changes: the rule reads a name before a row exists, and the regression set's
  `expected.json` is unchanged.
- A name whose letters and digits give the same <BOARDMODEL> as another board model's (`TBOX-A1` and `tbox a1`, or
  `CAL-1` and `CAL_1`) is still taken at entry and refused at freeze once the other has a version (AOI-TRN-040). The
  brief's item names the AOI-TRN-039 rule only; checking that one at entry too is left for Jay to decide.
- The Korean text of AOI-TRN-054 is a draft, marked unfinished in `aoi/i18n/aoi_ko.ts`, for a native speaker's review.
