-- REQ-INSP-010: every inspection carries the camera view it was taken from, Top, Side or Bottom, the key the
-- Inspection page's View box stores. Rows written before this migration keep NULL: their view was never recorded,
-- so none is guessed. The CHECK is tested against the existing rows (all NULL) on SQLite 3.37 or later.
ALTER TABLE inspections ADD COLUMN view TEXT CHECK (view IN ('Top', 'Side', 'Bottom'));
