-- REQ-SET-017 (S10): validation runs (test_runs, which leave the station in the AI Model Test screen's CSV and PDF
-- report) and alarms carry a UUID4 beside their local integer key, as the records of migration 0002 do, and a validation
-- run names the AI model it tested by UUID, as an inspection does since migration 0006 (NULL for runs stored before this
-- migration, and for a run with no AI model). ALTER TABLE cannot add a NOT NULL column without a default, so each table
-- is rebuilt with uuid NOT NULL and a unique index; every row keeps its id and values and gets a random UUID4. No foreign
-- key, trigger or view refers to either table, so the rebuild changes nothing else.

CREATE TABLE test_runs_0009 (
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, board_model TEXT,
    model_version TEXT, folder TEXT, metrics TEXT, results TEXT,
    uuid TEXT NOT NULL, model_uuid TEXT
);
INSERT INTO test_runs_0009(id, time, board_model, model_version, folder, metrics, results, uuid)
    SELECT id, time, board_model, model_version, folder, metrics, results,
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    FROM test_runs;
DROP TABLE test_runs;
ALTER TABLE test_runs_0009 RENAME TO test_runs;
CREATE UNIQUE INDEX test_runs_uuid ON test_runs(uuid);

CREATE TABLE alarms_0009 (
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, level TEXT, message TEXT, code TEXT,
    uuid TEXT NOT NULL
);
INSERT INTO alarms_0009(id, time, level, message, code, uuid)
    SELECT id, time, level, message, code,
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    FROM alarms;
DROP TABLE alarms;
ALTER TABLE alarms_0009 RENAME TO alarms;
CREATE UNIQUE INDEX alarms_uuid ON alarms(uuid);
