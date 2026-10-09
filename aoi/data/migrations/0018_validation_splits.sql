-- REQ-TRN-006 (S36): a frozen dataset version split once, seeded and recorded, into its training set and its locked
-- validation set. Rows never change: a version is split once, and a new split needs a new dataset version.

CREATE TABLE validation_splits (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    dataset_uuid TEXT NOT NULL UNIQUE,  -- one split per frozen version
    seed INTEGER NOT NULL,
    locked_by TEXT NOT NULL,
    locked_at TEXT NOT NULL
);
CREATE TABLE validation_split_items (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    split_uuid TEXT NOT NULL,
    item_uuid TEXT NOT NULL UNIQUE,     -- a dataset_items row, in one split only
    sha256 TEXT NOT NULL,
    part TEXT NOT NULL CHECK(part IN ('train','validation'))
);
CREATE INDEX validation_split_items_by_split ON validation_split_items(split_uuid);
CREATE INDEX validation_split_items_by_sha256 ON validation_split_items(sha256, part);
CREATE TRIGGER validation_splits_no_update BEFORE UPDATE ON validation_splits BEGIN
    SELECT RAISE(ABORT, 'a locked validation set is never changed'); END;
CREATE TRIGGER validation_splits_no_delete BEFORE DELETE ON validation_splits BEGIN
    SELECT RAISE(ABORT, 'a locked validation set is never unlocked'); END;
CREATE TRIGGER validation_split_items_no_update BEFORE UPDATE ON validation_split_items BEGIN
    SELECT RAISE(ABORT, 'a file of a locked split is never moved'); END;
CREATE TRIGGER validation_split_items_no_delete BEFORE DELETE ON validation_split_items BEGIN
    SELECT RAISE(ABORT, 'the files of a locked split are never deleted'); END;
