-- REQ-TRN-001 (S31): each sample records the SHA-256 of its source file, as read and checked before the copy and found
-- again in the source and in the copy after it, so an import can tell an image the board model already has and a
-- dataset can name each file by its content. NULL for a sample imported before this migration: never guessed.
ALTER TABLE samples ADD COLUMN sha256 TEXT;
CREATE INDEX samples_sha256 ON samples(board_model, sha256);
