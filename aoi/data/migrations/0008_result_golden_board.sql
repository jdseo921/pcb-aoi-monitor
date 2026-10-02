-- REQ-CMP-003 (S26b): the golden board a result was judged against, as the file the engine read (relative to the
-- workspace) and the SHA-256 of its bytes, so Compare shows that board and tells when the file has changed since;
-- NULL before this migration, and for a result judged without a golden board.
ALTER TABLE inspections ADD COLUMN reference_path TEXT;
ALTER TABLE inspections ADD COLUMN reference_sha256 TEXT;
