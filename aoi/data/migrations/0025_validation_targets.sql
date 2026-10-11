-- REQ-TST-008 (Customers & Launch, "Validation", step 2): the targets a customer agreed for a board model before its
-- validation is tested: the most missed Critical defects allowed, the highest false call rate (a fraction, 0.05 for
-- 5 %) and the longest engine time per image at the 95th percentile, in seconds; with whom they were agreed, as typed,
-- and who recorded them and when (UTC). The newest row of a board model is in force; a validation run keeps a copy of
-- the row in force when it started, so targets recorded later never change a run made before them. Every row is also
-- an audit entry (validation.targets); rows are only ever added.

CREATE TABLE validation_targets (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    board_model TEXT NOT NULL,
    missed_critical INTEGER NOT NULL CHECK(missed_critical >= 0),
    false_call_rate REAL NOT NULL CHECK(false_call_rate >= 0 AND false_call_rate <= 1),
    seconds_per_image REAL NOT NULL CHECK(seconds_per_image > 0),
    agreed_with TEXT NOT NULL,
    user TEXT NOT NULL,
    time TEXT NOT NULL
);
CREATE INDEX validation_targets_board_model ON validation_targets(board_model, id);
