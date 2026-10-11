-- REQ-INSP-017 (ADR 0014): the start-of-shift check of a board model. Its master samples, a known-OK board and a
-- known-NG board for each Critical defect type labelled, are judged with the engine in use; `passed` is 1 only when
-- every verdict was right. `inputs` (JSON) is what judged them, as Inspector.inputs gives it: the AI model's and the
-- recipe revision's UUIDs, the Golden board's path relative to the workspace and the scale; a check stops counting
-- once any of them changes. `rows` (JSON) holds each sample's UUID, file, expected and given verdict. Every check is
-- also an audit entry (inspection.shift_check); rows are only ever added.

CREATE TABLE shift_checks (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    board_model TEXT NOT NULL,
    time TEXT NOT NULL,
    user TEXT NOT NULL,
    passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
    inputs TEXT NOT NULL,
    rows TEXT NOT NULL
);
CREATE INDEX shift_checks_board_model ON shift_checks(board_model, id);
