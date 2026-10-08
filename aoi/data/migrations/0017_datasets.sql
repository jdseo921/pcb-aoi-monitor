-- REQ-TRN-005 (S35): a frozen dataset version, DS-<BOARDMODEL>-<REV>-<VIEW>-v<N>, and its files as its manifest lists
-- them. Rows never change: a later label or file change goes into the next version.

CREATE TABLE datasets (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    board_model TEXT NOT NULL,
    revision TEXT NOT NULL,
    view TEXT NOT NULL,
    version INTEGER NOT NULL,
    customer TEXT NOT NULL,
    allowed_uses TEXT NOT NULL,         -- JSON list
    agreement_check_uuid TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    frozen_by TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    UNIQUE(board_model, view, version)
);
CREATE TABLE dataset_items (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    dataset_uuid TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    sample_uuid TEXT NOT NULL,
    label_uuid TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('OK','NG')),
    defect_type TEXT,
    boxes TEXT NOT NULL,                -- JSON list of {x, y, w, h, dct_type, severity}
    labelled_by TEXT,                   -- none for a label carried over by migration 0014
    checked_by TEXT
);
CREATE INDEX dataset_items_by_dataset ON dataset_items(dataset_uuid);
CREATE TRIGGER datasets_no_update BEFORE UPDATE ON datasets BEGIN
    SELECT RAISE(ABORT, 'a frozen dataset version is never changed'); END;
CREATE TRIGGER datasets_no_delete BEFORE DELETE ON datasets BEGIN
    SELECT RAISE(ABORT, 'frozen dataset versions are never deleted'); END;
CREATE TRIGGER dataset_items_no_update BEFORE UPDATE ON dataset_items BEGIN
    SELECT RAISE(ABORT, 'a file of a frozen dataset version is never changed'); END;
CREATE TRIGGER dataset_items_no_delete BEFORE DELETE ON dataset_items BEGIN
    SELECT RAISE(ABORT, 'the files of a frozen dataset version are never deleted'); END;
