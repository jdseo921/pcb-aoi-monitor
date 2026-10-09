# ADR 0009: How labels, their checks and frozen dataset versions are stored

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-08
- Decides: the product owner (Jay), until a tech lead joins
- Related: stages S32, S34 and S35 of the Stage 1 plan; REQ-TRN-002, -003, -004, -005, -016; sketches
  `docs/sketches/training-labels.md` and `docs/sketches/training-datasets.md`; [ADR 0002](0002-local-sign-in.md)
  (the second user is a picked name); [ADR 0004](0004-schema-v1.md) (numbered migrations, UUIDs, UTC times)

## Context

Until S32 a sample held one label, which Mark NG overwrote. REQ-TRN-002 to -005 and -016 need a label's history and
its boxes, who labelled it and who checked it, a random share of OK labels to check, kept on record, a stored
agreement check of two labellers, and a named version of the data whose record never changes and whose files can be
verified. Training reads labels on every run, so the current label must stay one join away.

## Decision

1. **Labels and defect boxes are rows with history** (migration 0014). `labels` holds uuid, sample_uuid, label (OK, NG
   or UNSURE), defect_type, labelled_by (a user's UUID), at_utc and superseded_by; `defect_boxes` holds uuid,
   sample_uuid, label_uuid (the label row it was drawn with), x, y, w, h, dct_type, severity (the type's in
   `aoi/defects.py`, never the caller's), labelled_by, at_utc and superseded_by. A sample's current label is its one row
   with superseded_by NULL (a partial unique index). A relabel or a box change (`Database.add_label`) marks the current
   label row and its boxes superseded by the new row's UUID and adds the new rows, in one transaction. x, y, w, h are
   whole pixels of the image as the decoder returns it, turned by its EXIF Orientation: what a screen shows and
   inspection sees; the size a box is checked against is read without decoding (`imaging.file_header`: the first MiB of
   most files, the whole of a TIFF or of a JPEG with large segments before its frame header, and a PNG's chunk headers
   across the file, up to 65,536 chunks), width and height swapped for orientations 5 to 8, the Orientation read as
   OpenCV 5.0, libpng and libtiff read it; still unmatched are an EXIF segment past a JPEG's first MiB when its frame
   header lies inside it, an eXIf chunk over libpng's chunk limit, an eXIf after a PNG's first 65,536 chunks and a JPEG
   with more than 65,536 markers before its scan. Triggers refuse every DELETE and every UPDATE but that one mark, made
   once. No foreign key refers to `samples`, so a removed sample keeps its history.
2. **`samples.label` and `samples.defect_type` stay as the import wrote them.** Every sample read joins the current
   label row instead; an UNSURE image is in no OK or NG list, so training leaves it out. An import labels an image OK or
   NG only, and its first label row names the user the import ran as, the one who pressed Import (`labelled_by`); UNSURE
   is only ever a later label of a labeller. Each sample stored before migration 0014 gets one label row with its label
   and defect type, at its added_at, labelled_by NULL. Mark OK and Mark NG add no row for the label and type a labeller
   gave already, so its check stays; a label carried over with no labeller is labelled again, so it can be checked.
3. **A check names the label row it confirms** (migration 0015). `label_checks` holds one row per label row
   (label_uuid UNIQUE) with checked_by, so a relabel is unchecked until checked again; `AppContext.check_label`
   refuses the row's labeller (AOI-TRN-033). `ok_check_draws` stores each draw of OK labels to check: board model,
   view (`side`), seed, the OK label count, the samples drawn, who drew and when. `draw_ok_checks` draws with
   `random.Random(seed)` from the view's OK samples not drawn before, in id order, as many as the drawn ones still OK
   fall short of 10 % of the OK labels, rounded up; a later draw adds samples and never replaces one. The seed, the
   count and the samples drawn are stored and audited; the pool drawn from is not, so the stored samples, not a
   replay of the seed, are the record of a draw. The `seed` argument is for tests: a screen draws with a new seed and
   never shows or asks for one. `labels_ready_to_freeze` is True once every NG label and that many drawn OK labels are
   checked, and never for a view with no OK or NG label.
4. **Agreement checks are stored on their own** (migration 0016). `calibration_sets` holds 100 images (proposed) of
   one board model, each labelled OK or NG when the set is made; `blind_labels` holds each user's own label of each
   image, apart from `labels`, once per set, image and user; `agreement_checks` holds the counts, the targets (98 %
   and 90 %, proposed), whether both were reached (`agreed`), the two labellers, who ran it and when. Every check is
   stored, agreed or not, keyed by its set and board model. The newest check of the board model whose set holds an
   image of a view decides whether a version of that view can be frozen: a newer check short of the targets refuses a
   freeze until a newer one reaches them.
5. **A frozen version is a record, its files and a manifest** (migration 0017). `datasets` holds the name
   DS-<BOARDMODEL>-<REV>-<VIEW>-v<N> (unique), the version number (unique per board model and view), customer, allowed
   uses, the UUID of the agreement check that decided (decision 4), the manifest's path and SHA-256, who froze it and
   when; `dataset_items` holds one row per OK or NG file of the view: its path relative to the workspace, SHA-256,
   sample, label row, label, defect type, boxes, labeller and checker. <BOARDMODEL> is the board model's ASCII letters
   and digits in upper case (`datasets.token`); a board model whose name has none, such as one in Korean only, is
   refused (AOI-TRN-039), a rule open for Jay, and so is one whose letters and digits another board model's frozen
   versions use (AOI-TRN-040), so one token names one board model's versions. `freeze_dataset` runs the refusals that
   need no file first, so a freeze they refuse reads no image file first, and hashes the files with no lock held; then,
   holding the database lock (`Database.locked`), one write transaction finds N, checks the gate again, reads the labels
   and, in one query, the boxes, stores the rows with the `dataset.freeze` audit entry and moves
   `datasets/<name>/manifest.json` into place just before the commit (`atomic.staged`); a failed commit puts back the
   manifest it replaced before the lock is released. A freeze that dies before the move leaves no manifest; one that
   dies between the move and the commit leaves a manifest no row names, which the next freeze of that name replaces. A
   second freeze of the view waits for the first, and only a `datasets` row refuses a name. The lock is held about 0.1 s
   per 1,000 files, and every other database call waits. A manifest that cannot be written is AOI-TRN-041 (AOI-TRN-042
   for a path too long). A version's rows and manifest never change; a later label change goes into v<N+1>, and so does
   a freeze with nothing changed, so that a version can carry a newer agreement check.
6. **The manifest names the workspace's sample files; it does not copy them.** The app never changes or removes a
   sample file (`delete_sample` leaves it in place), so a file changes only outside the app; `verify_dataset` re-hashes
   the manifest and each file against the hashes in `datasets` and `dataset_items` and lists the files that changed or
   are missing. The old bytes of such a file cannot be recovered from the workspace, so the workspace needs a backup.
7. **Every table here is append-only**, by triggers on UPDATE and DELETE (decision 1's mark aside); every row
   carries a UUID4, and every time is UTC with an offset (ADR 0004).
8. **Migrations 0014 to 0017** come after S29's `0012_board_model_scale.sql` and S31's `0013_sample_sha256.sql`.
   They were numbered 0012 to 0015 on this work's own branch, after 0011 on its base, and renumbered when it was
   rebased onto S29 and S31; no test names a number (a test finds a migration by its name).

## Alternatives considered

- **Overwrite `samples.label` and keep history in the audit trail only.** The audit trail is not what training
  reads, and an entry is not a row a version can name; label rows keep history where the label is read.
- **Drop `samples.label`.** SQLite would rebuild the table; the column still tells what the import gave.
- **A checked_by column on `labels`.** It would need a second kind of UPDATE on a row that otherwise never changes;
  a table of checks keeps decision 1's rule.
- **Count any OK labels a checker picks.** The checker could pick easy ones; a seeded draw is random, and the samples
  it drew are stored.
- **Freeze with the newest check that reached the targets.** A newer check that did not would then not stop a freeze.
- **Write the manifest before the version's transaction and remove it when that fails.** A freeze that died between
  the two left a manifest no row named, and every later freeze of that version was refused.
- **Boxes in the pixels stored, before the EXIF Orientation is applied.** A box drawn on the image shown would be
  turned back for storing and turned again for every use; inspection and the label editor (S33) see the turned image.
- **Agreement counts as columns of `datasets`.** Checks are run before any version exists and one check can serve
  several versions, so the version names the check.
- **Copy each file into the version.** It would double the disk a board model's 20 MP images take; verification
  finds a changed file instead.

## Consequences

- No label, box, check, draw, set, blind label, agreement check or version is edited or removed through the app or
  through SQL while the triggers stand; a wrong label is corrected by a new label.
- A label carried over by migration 0014 has no labeller, cannot be checked (AOI-TRN-034) and is labelled again
  first; an existing workspace's NG labels stop a freeze until then.
- A sample file changed or removed after a freeze shows in `verify_dataset`; the version's rows stay as they were, and
  the file's old bytes are only in a backup of the workspace.
- A workspace migrated by a build of this work's own branch, with the numbers 0012 to 0015, is refused by a build
  with the numbers of decision 8 (AOI-SET-002 or AOI-SET-003, `aoi/data/migrate.py`), so such a workspace was for
  development only.
- The plan's S36 (validation split and lock) starts from `datasets` and `dataset_items`; S37's encrypted
  per-customer store (REQ-TRN-017) may move the files a version names, and its own record decides that.
