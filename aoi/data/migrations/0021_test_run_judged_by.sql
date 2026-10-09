-- REQ-TST-005 (S46): a validation run stores what judged every row: the recipe revision and its UUID, the Golden
-- board, the scale and whether the AI check ran (aoi/core/inspector.JudgedBy, as JSON); NULL for runs before it.

ALTER TABLE test_runs ADD COLUMN judged_by TEXT;
