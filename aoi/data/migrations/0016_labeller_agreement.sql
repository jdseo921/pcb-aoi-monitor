-- REQ-TRN-016 (S34): a calibration set is a fixed list of images of one board model (100, proposed); a blind label is
-- one user's own label of one of its images, apart from `labels`, made once; an agreement check holds the counts, the
-- targets and whether both were reached, and the dataset version frozen next names it (S35). Rows never change.

CREATE TABLE calibration_sets (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    board_model TEXT NOT NULL,
    sample_uuids TEXT NOT NULL,         -- JSON list of the samples in the set
    made_by TEXT NOT NULL,
    at_utc TEXT NOT NULL
);
CREATE TABLE blind_labels (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    set_uuid TEXT NOT NULL,
    sample_uuid TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('OK','NG')),
    defect_type TEXT,
    labelled_by TEXT NOT NULL,
    at_utc TEXT NOT NULL,
    UNIQUE(set_uuid, sample_uuid, labelled_by)
);
CREATE TABLE agreement_checks (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    set_uuid TEXT NOT NULL,
    board_model TEXT NOT NULL,
    labeller_a TEXT NOT NULL,
    labeller_b TEXT NOT NULL,
    images INTEGER NOT NULL,
    ok_ng_agree INTEGER NOT NULL,       -- images both labelled OK or both NG
    both_ng INTEGER NOT NULL,           -- images both labelled NG
    type_agree INTEGER NOT NULL,        -- of those, the images both gave the same defect type
    ok_ng_target INTEGER NOT NULL,      -- percent
    type_target INTEGER NOT NULL,       -- percent
    agreed INTEGER NOT NULL CHECK(agreed IN (0, 1)),
    run_by TEXT NOT NULL,
    at_utc TEXT NOT NULL
);
CREATE TRIGGER calibration_sets_no_update BEFORE UPDATE ON calibration_sets BEGIN
    SELECT RAISE(ABORT, 'a calibration set is never changed'); END;
CREATE TRIGGER calibration_sets_no_delete BEFORE DELETE ON calibration_sets BEGIN
    SELECT RAISE(ABORT, 'calibration sets are never deleted'); END;
CREATE TRIGGER blind_labels_no_update BEFORE UPDATE ON blind_labels BEGIN
    SELECT RAISE(ABORT, 'a blind label is never changed'); END;
CREATE TRIGGER blind_labels_no_delete BEFORE DELETE ON blind_labels BEGIN
    SELECT RAISE(ABORT, 'blind labels are never deleted'); END;
CREATE TRIGGER agreement_checks_no_update BEFORE UPDATE ON agreement_checks BEGIN
    SELECT RAISE(ABORT, 'an agreement check is never changed'); END;
CREATE TRIGGER agreement_checks_no_delete BEFORE DELETE ON agreement_checks BEGIN
    SELECT RAISE(ABORT, 'agreement checks are never deleted'); END;
