# ADR 0022: One count of the images a board model needs, and What is missing

- Status: Proposed under Jay's instruction of 2026-10-13 14:22 UTC, item B3 of the business-readiness brief (finding
  F6): "one source of truth for how many images a board model needs, computed from the constants in
  aoi/core/datasets.py, and one sentence everywhere it is shown. Home and Training show a live 'What is missing'
  checklist for the selected board model: each line a count against its requirement (OK images, NG images, NG images
  with boxes, a locked validation set, a trained AI model, an active AI model) and the one button that fixes it. For a
  Trial version the checklist shows only what Trial needs; for Validated it adds the second-user checks and the
  agreement check." Jay's merge of this record accepts it.
- Date: 2026-10-13
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-021 (new), REQ-TRN-004, REQ-TRN-005, REQ-TRN-006, REQ-TRN-007, REQ-TRN-016, ADR 0018 (the first AI
  model goes live), ADR 0020 (Trial versions, B1), Customers & Launch, "Validation"

**Numbering.** As for ADR 0020: Jay's decision record is not in the repository, and this record says how B3 is built.
Where Jay's record decides otherwise, Jay's record wins and this one is changed to match.

## Context

How many images a board model needs was written out in three places and they disagreed (F6): Home asked for "at least
70 OK boards", computed as `VALIDATION_OK + TRAIN_OK` in aoi/ui/main_window.py; Training's tip said "20 OK images or
more in a dataset version's training set" and its empty sample table "at least 20 OK boards", both literals; the
README and the customer document said 70 in words of their own. None said what a Validated version needs beyond the OK
images, and nothing showed a person alone what step comes next: they found each refusal by pressing the button it
refuses.

## Decision

1. **One source.** aoi/core/datasets.py holds the counts, and `datasets.needs()` the one sentence that states them,
   filled from them: `OK_NEEDED = VALIDATION_OK + TRAIN_OK` (70: the 50 a validation set locks and the 20 a training
   set needs, of one view, since a version holds one view); `NG_NEEDED = 1`; and `labels.CALIBRATION_IMAGES` (100), the
   images a calibration set draws for the agreement check, which only a Validated version needs. The sentence, on Home,
   on Training and in the README, the engineer manual and the customer document (English and Korean): "A board model
   needs at least 70 OK images of one view (20 to train, 50 held out to test) and 1 or more NG images with every
   defect boxed; a Validated version also needs 100 images labelled OK or NG for the agreement check." A test fails
   when a screen writes a count of OK images of its own, or a document leaves the sentence out.
2. **Why one NG image.** Nothing refused a board model with no NG image before. With one, its validation set holds it
   (30 % of the NG, rounded up), so an AI model test counts missed defects rather than none, and a calibration set
   holds one image both labellers can call NG, without which an agreement check never reaches its defect-type target
   (`labels.agreement`). Customers & Launch asks for "every NG sample they have"; one is the least the steps need, not
   a target, and the sentence says "or more".
3. **What is missing is read, never stored.** `AppContext.missing(board_model, trial)` counts, writing nothing: OK
   images, NG images, NG images with every defect boxed, then for a Validated version the NG labels and 10 % of the OK
   labels checked by a second user, the images labelled OK or NG for a calibration set and an agreement check that
   reached its targets, then a locked validation set, a trained AI model and, for a Validated version, an active AI
   model. Each line has `have`, `need`, the one `fix` that takes it further and, for a line not met, `after`: the first
   line not met that its step waits for, as the step's own refusal does. Freeze Dataset… waits for the images and boxes
   and, for a Validated version, the checks and the agreement check (which `_refuse_freeze` refuses without), and for 70
   OK images and every defect boxed, without which the version frozen is not one to split and train from; Split and Lock
   Validation Set… waits for nothing, its version frozen already; Start Training waits for the locked validation set and
   Activate AI Model for a trained AI model. So images added after a freeze, which the first lines count for a next
   version, never grey the steps of the version frozen before. The images for a calibration set are a line of their own:
   70 OK and 1 NG are 71 images, and a calibration set draws 100, so without the line a Validated board model would show
   every image line met and an agreement check it cannot run; it holds back the agreement check alone, so once a check
   reached its targets, fewer images later do not grey Freeze Dataset….
4. **Trial lists what Trial needs.** A Trial version needs no second-user check and no agreement check (ADR 0020), and
   its AI model never goes live, so its list ends at a trained AI model, of either kind. The Validated list counts only
   Validated versions, AI models trained from them and an active one that is not a Trial AI model. With no kind picked,
   the list is of the newest version's kind, Validated before the first freeze; Validated or Trial on a list picks the
   other for that list, Home's and Training's each, kept while the board model stays in the header.
5. **One view.** The counts are of the view of the newest version of the list's kind whose validation set is locked and
   which Training trains from (Decision 6), else of the newest version of the list's kind, else of the view with the
   most images labelled OK or NG, Top first among equals. A Trial version of another view, newer, does not move the
   Validated list. The images for a calibration set count every view, as a calibration set draws from all.
6. **A locked validation set you can train from.** The line is met by a locked version of the list's kind that Training
   trains from for the use "own": `_train_refusal`, the checks `_training_set` makes from the rows, writing nothing,
   finds none (its store and allowed uses, AOI-TRN-046; `TRAIN_OK` OK files in its training set, AOI-TRN-045; no
   training file locked for validation, AOI-TRN-043). A locked version with fewer, which training refuses, does not meet
   it. Its fix is Split and Lock Validation Set… for the newest unlocked version of the view and kind whose store and
   uses fit and whose split leaves `TRAIN_OK` OK files for training (`datasets.train_ok`: its OK files less the 50 drawn
   for validation, or more where earlier splits locked its files' SHA-256 again), else Freeze Dataset…, opened for a
   Trial version when the list is a Trial one. The Split sheet says the same: a version of 50 OK images may be locked,
   and the sheet then says how many OK images its training set would hold, fewer than the 20 training needs, and that a
   version of 70 OK images or more is one to train from (`AppContext.train_ok_after_split`).
7. **The buttons.** Each fix is the step Training already takes, under the name its control there has: Add OK Images…,
   Add NG Images…, Draw Boxes › (the first NG image of the view with no box, in the label editor), Show Unchecked ›,
   Draw OK Labels to Check, Open Labeller Agreement ›, Freeze Dataset…, Split and Lock Validation Set…, Start Training
   (from the locked version) and Activate AI Model (the newest AI model of the list's kind). On Home the button opens
   Training first. A button is greyed while its line waits for another (Decision 3), which the line names under it and
   its tooltip repeats, and for a role that may not make the call, with the refusal as its tooltip and on the status bar
   on a press (REQ-USR-001), as every greyed control is. A press that cannot take its step now says why on the status
   bar: blind labelling open, an import, draw or freeze of the page running, or a training run under way.
8. **Where it shows.** Home: under the six cards, for every role. The cards and the list scroll inside Home, under its
   title, so the list is below the fold at 1366 x 768 and its last lines at 1920 x 1080 too. Home is no taller than the
   window: were it taller, the area round the pages would be as tall, and the page opened after Home would be laid out
   at that height before its own (a press on Compare's Try panel at that moment missed it). Training: a third tab, What is missing, after Samples and
   Datasets, in an area that scrolls rather than make the page taller; the list is read again whenever the tab is shown
   and on every refresh of the page while it is. Once the list's AI model is there (an active one, or for a Trial list a
   trained one), the line above the list says so and counts what a next version still needs.

## Consequences

- No change to what is stored, refused or judged: no migration, no audit entry of its own (the steps its buttons take
  audit themselves), no verdict changed, the synthetic regression set unchanged.
- The Training tab bar has three tabs; the blind panel is the stack's fourth page.
- Home's cards and list scroll inside the page, under its title, with a scroll bar of their own; no other page moved:
  the approved screenshots of every other page are those approved before this record, but Training's.
- Left out, and named here: a board model in no customer's dataset store is not a line of its own. The Freeze sheet,
  which Freeze Dataset… opens, already says "its images are in no customer's dataset store; an Admin moves them in"
  (AOI-TRN-027), and since ADR 0021 a customer's board model is made in its store.

## Alternatives considered

- **Counting every view together.** Rejected: a version, its validation set and its training set are of one view, so
  80 OK images split over Top and Side freeze into no trainable version, and a total would say otherwise.
- **The list beside the Samples table, always shown on Training.** Rejected: the Samples tab is full at 1366 px, and a
  third tab keeps Training no taller (A7).
- **No NG requirement.** Rejected for the reasons in Decision 2.
