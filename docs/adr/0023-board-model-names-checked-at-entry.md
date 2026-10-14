# ADR 0023: A board model's name is checked where it is entered

- Status: Proposed under Jay's instruction of 2026-10-13 14:22 UTC, item B4 of the business-readiness brief (D4 part,
  finding F9): "a board model name is validated when it is entered, with the same rule freeze applies today
  (AOI-TRN-039), and the message says what a valid name looks like; a Korean-only name is refused at entry, never
  later. Add a test with the names that used to slip through." Jay's merge of this record accepts it. Decisions 6 to 8
  are Jay's choice of 2026-10-13 19:58 UTC on the question "Refuse board model names at entry when another board
  model's version name would clash?": "Refuse at entry: a small follow-up PR moves the AOI-TRN-040 check into New board
  model and the import paths, and normalises look-alike names."
- Date: 2026-10-13
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-005, REQ-TRN-001, REQ-TRN-017, ADR 0009 (labels, checks and dataset versions), ADR 0021 (the New
  board model dialog), AOI-TRN-054 (new), AOI-TRN-055 (new), AOI-TRN-056 (new), AOI-TRN-039, AOI-TRN-040,
  AOI-TRN-019, AOI-TRN-005

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
   with AOI-TRN-039), then AOI-TRN-005 for a name that differs from an existing one only in case (as before), then
   AOI-TRN-055 and AOI-TRN-056 (decisions 6 and 7). Every
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
   itself, deciding with the form shown: the name and customer fields pass it on, and the dialog gives it to Create
   (`make`), which does nothing for a refused name, and no default button is pressed after it. The fields no longer
   call Create on their own Enter, which in Customer made a customer's store and then pressed the key step's default
   button, Save to File… (review of B4). A focused button takes Enter as before, and the Customer list's popup the
   Enter that picks from it.
5. **A name the workspace already holds is kept.** A board model made before this rule under a name it refuses keeps
   its name, imports, takes a reference and inspects as before, and + New with its name, typed exactly, chooses it; only
   freeze refuses it, with AOI-TRN-039, as it did, saying to import its images under a name with a Latin letter or
   digit. AOI-TRN-039 stays for that case. Refusing such workspaces at start-up, or renaming their board models, was
   not chosen: a rename touches folders, AI model files and records, and Jay asked for a check at entry.
6. **A name that reads the same as an existing one is refused (AOI-TRN-055).** Two names are compared as they read
   on a screen (`looks` in `aoi/core/services.py`): in NFKC, case folded, so that full-width letters and digits read as
   A to Z and 0 to 9, a decomposed Hangul syllable (as a macOS file name gives it) as the composed one, a ligature or a
   superscript digit as its letters or digit, and ß as ss; with the characters that show nothing dropped (a zero-width
   space or joiner, a soft hyphen, a direction mark or override, a byte order mark, a Hangul filler, a variation
   selector, the Braille blank); and with every run of spaces of any kind (a no-break or ideographic space, two spaces)
   as one space, none at the ends. A new name that reads the same as an existing one is refused, naming that board
   model, saying what was set aside to compare them, and saying to select it in the top bar or to type a name that
   differs in a letter A to Z or a digit 0 to 9. Some names it refuses differ in more than looks (`Boß-1` and
   `BOSS-1`, `TBOX-A¹` and `TBOX-A1`); the message says so, and refusing too much is the safe side for a name that
   names folders and dataset versions. "Normalises" is read as comparing the normal forms, not storing one: the name is
   kept as typed when it is taken, so the folders, files and records of a board model never carry a name other than
   the one its Engineer typed, and nothing made before is renamed. Jay's review of this record confirms that reading.
7. **A name whose versions would take another board model's names is refused (AOI-TRN-056).** A new name whose
   `datasets.token` equals an existing board model's (`TBOX-A1` and `tbox a1`, `CAL-1` and `CAL_1`, `TBOX-A1` and
   `TBOX-A1 메인보드`, `보드 1` and `기판 1`) is refused, naming that board model and the DS-<BOARDMODEL>-… both would
   share, and saying to select it if it is the same board, or to give a name whose letters A to Z or digits 0 to 9
   differ (`Café-1` and `Caf-1` share DS-CAF1: é is not one of A to Z).
   This is freeze's AOI-TRN-040 test, made against every existing board model, with versions or none: at entry no one
   knows which of the two will be frozen first, and before, the second found out at freeze, after labelling. Freeze
   keeps AOI-TRN-040 for board models made before this rule.
8. **The most specific refusal is given.** Case first (AOI-TRN-005, which says why case matters on Windows), then how
   it looks (AOI-TRN-055), then the letters and digits (AOI-TRN-056). AOI-TRN-056 would refuse many of the names the
   first two refuse (every case variant, and a look-alike that differs in a character that shows nothing, a space or a
   decomposed syllable), but its message sends the Engineer to look for a letter A to Z or a digit that differs, which
   there they cannot see.

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
- Two board models made before decisions 6 and 7 whose names clash or look alike are both kept: each imports, takes a
  reference and inspects as before, and freeze refuses the second once the first has a version (AOI-TRN-040), as it
  did. The tests that made such a pair through a call that now refuses it make the second as made before
  (`tests/test_datasets.py`).
- A name holding a character that shows nothing, or a no-break space, with no existing name like it, is still taken,
  as typed: it is a name of its own. Whoever types the plain form later is refused with AOI-TRN-055, which names the
  board model it looks like, to be selected in the top bar. Refusing such characters in every new name was not
  chosen: Jay's choice names look-alikes of existing names.
- Letters of another alphabet that look like Latin ones (a Cyrillic А for A) are not compared as alike: Unicode's list
  of such letters runs to thousands, NFKC maps none of them, and a name in such letters only is refused already
  (AOI-TRN-054). A name mixing them with Latin ones (`TBOX-А1` with a Cyrillic А) is taken beside `TBOX-A1`, and its
  versions are named DS-TBOX1-…. Latin letters and digits that look alike in some fonts (O and 0, l and 1:
  `TB0X-A1`) are different letters, and such a name is taken. A name holding a right-to-left override, which shows
  its letters in reverse order, is taken too: the override shows nothing and is dropped, and what is left reads
  differently. Refusing these at entry is for Jay to ask for; none is a name a station's keyboard types by mistake.
- AOI-TRN-054's example, "TBOX-A1 메인보드", is refused with AOI-TRN-056 where TBOX-A1 exists. It stays: the example
  shows how Korean letters sit beside Latin ones, and AOI-TRN-056 says what to change if it is typed there.
- The Korean text of AOI-TRN-054, AOI-TRN-055 and AOI-TRN-056 is a draft, marked unfinished in `aoi/i18n/aoi_ko.ts`,
  for a native speaker's review.
