-- REQ-INSP-020 (ADR 0024 D30): the SHA-256 of the image file a record judged, for a board taken from the watched input
-- folder, saved with the record in its transaction, so the line never inspects the same image twice; NULL for a board
-- loaded by hand and for every record before this migration.

ALTER TABLE inspections ADD COLUMN image_sha256 TEXT;
CREATE INDEX inspections_image_sha256 ON inspections(image_sha256) WHERE image_sha256 IS NOT NULL;
