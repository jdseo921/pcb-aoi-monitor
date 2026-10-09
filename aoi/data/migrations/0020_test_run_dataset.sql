-- REQ-TST-001 (S44): a validation run on a frozen dataset version's locked validation set names the version; a run
-- on a labelled folder leaves it NULL.

ALTER TABLE test_runs ADD COLUMN dataset_uuid TEXT;
