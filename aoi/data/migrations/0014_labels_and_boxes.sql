-- REQ-TRN-002, REQ-TRN-003 (S32): an image's label (OK, NG or UNSURE) and its defect boxes, with history. A relabel or a
-- box change adds a label row, and the boxes drawn with it, and marks the rows they replace superseded by the new label
-- row's uuid; nothing is deleted. A sample's current label is its one label row whose superseded_by is NULL, which
-- training and every list read; samples.label and samples.defect_type keep what the import wrote and are not changed
-- again. labelled_by is the user's uuid. Every sample stored before this migration gets one current label row with its
-- label and defect type at the time it was added, labelled_by NULL: who labelled it was not recorded, never guessed.
-- A row keeps its sample's uuid when the sample is removed, so no foreign key refers to samples.

CREATE TABLE labels (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    sample_uuid TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('OK','NG','UNSURE')),
    defect_type TEXT,                   -- an NG image's defect type (DCT), as the import or a relabel gave it
    labelled_by TEXT,
    at_utc TEXT NOT NULL,
    superseded_by TEXT
);
CREATE UNIQUE INDEX labels_current ON labels(sample_uuid) WHERE superseded_by IS NULL;  -- one current label each
CREATE INDEX labels_sample ON labels(sample_uuid);
CREATE TABLE defect_boxes (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    sample_uuid TEXT NOT NULL,
    label_uuid TEXT NOT NULL,           -- the label row the box was drawn with
    x INTEGER NOT NULL CHECK(x >= 0), y INTEGER NOT NULL CHECK(y >= 0),
    w INTEGER NOT NULL CHECK(w > 0), h INTEGER NOT NULL CHECK(h > 0),
    dct_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('Critical','Major','Minor')),
    labelled_by TEXT,
    at_utc TEXT NOT NULL,
    superseded_by TEXT
);
CREATE INDEX defect_boxes_sample ON defect_boxes(sample_uuid);

-- History stays as written: a row is never deleted, and the one change it takes is being marked superseded, once.
CREATE TRIGGER labels_no_delete BEFORE DELETE ON labels BEGIN SELECT RAISE(ABORT, 'labels are never deleted'); END;
CREATE TRIGGER labels_no_update BEFORE UPDATE ON labels WHEN OLD.superseded_by IS NOT NULL OR NEW.superseded_by IS NULL
    OR NEW.id IS NOT OLD.id OR NEW.uuid IS NOT OLD.uuid OR NEW.sample_uuid IS NOT OLD.sample_uuid
    OR NEW.label IS NOT OLD.label OR NEW.defect_type IS NOT OLD.defect_type OR NEW.labelled_by IS NOT OLD.labelled_by
    OR NEW.at_utc IS NOT OLD.at_utc BEGIN SELECT RAISE(ABORT, 'a label is never changed: a relabel adds a row'); END;
CREATE TRIGGER defect_boxes_no_delete BEFORE DELETE ON defect_boxes BEGIN
    SELECT RAISE(ABORT, 'defect boxes are never deleted'); END;
CREATE TRIGGER defect_boxes_no_update BEFORE UPDATE ON defect_boxes WHEN OLD.superseded_by IS NOT NULL
    OR NEW.superseded_by IS NULL OR NEW.id IS NOT OLD.id OR NEW.uuid IS NOT OLD.uuid
    OR NEW.sample_uuid IS NOT OLD.sample_uuid OR NEW.label_uuid IS NOT OLD.label_uuid OR NEW.x IS NOT OLD.x
    OR NEW.y IS NOT OLD.y OR NEW.w IS NOT OLD.w OR NEW.h IS NOT OLD.h OR NEW.dct_type IS NOT OLD.dct_type
    OR NEW.severity IS NOT OLD.severity OR NEW.labelled_by IS NOT OLD.labelled_by OR NEW.at_utc IS NOT OLD.at_utc BEGIN
    SELECT RAISE(ABORT, 'a defect box is never changed: a new box set adds rows'); END;

INSERT INTO labels(uuid, sample_uuid, label, defect_type, labelled_by, at_utc)
    SELECT lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))),
    uuid, label, defect_type, NULL, added_at FROM samples ORDER BY id;
