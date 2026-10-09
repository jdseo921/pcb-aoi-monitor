-- REQ-TRN-004 (S34): who checked a label, and which OK labels were drawn at random for a check. A check names the
-- label row it confirms, so a relabel, which adds a row, needs a check of its own; checked_by is a user's uuid and is
-- never the label row's labelled_by (AppContext.check_label refuses that). A draw records its seed, the number of OK
-- labels it drew from and the samples it drew; a later draw adds samples, it never replaces one. Rows are never
-- changed or deleted.

CREATE TABLE label_checks (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    label_uuid TEXT NOT NULL UNIQUE,
    sample_uuid TEXT NOT NULL,
    checked_by TEXT NOT NULL,
    at_utc TEXT NOT NULL
);
CREATE TABLE ok_check_draws (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    board_model TEXT NOT NULL,
    side TEXT NOT NULL,
    seed INTEGER NOT NULL,
    ok_labels INTEGER NOT NULL,         -- the OK labels of the board model and view when drawn
    sample_uuids TEXT NOT NULL,         -- JSON list of the samples drawn, in the order drawn
    drawn_by TEXT NOT NULL,
    at_utc TEXT NOT NULL
);
CREATE TRIGGER label_checks_no_update BEFORE UPDATE ON label_checks BEGIN
    SELECT RAISE(ABORT, 'a label check is never changed'); END;
CREATE TRIGGER label_checks_no_delete BEFORE DELETE ON label_checks BEGIN
    SELECT RAISE(ABORT, 'label checks are never deleted'); END;
CREATE TRIGGER ok_check_draws_no_update BEFORE UPDATE ON ok_check_draws BEGIN
    SELECT RAISE(ABORT, 'a draw is never changed'); END;
CREATE TRIGGER ok_check_draws_no_delete BEFORE DELETE ON ok_check_draws BEGIN
    SELECT RAISE(ABORT, 'draws are never deleted'); END;
