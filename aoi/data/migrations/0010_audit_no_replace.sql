-- REQ-LOG-004 (#196): an audit entry cannot be replaced. Migration 0003's triggers refuse UPDATE and DELETE, but
-- INSERT OR REPLACE (or REPLACE INTO) reusing an entry's uuid or id removed the entry without firing the delete trigger
-- (SQLite fires it only with PRAGMA recursive_triggers, which is off by default) and wrote a forged entry in its place,
-- with another time, role, values and reason. This trigger refuses an insert whose uuid, or whose id when one is given,
-- an entry already has; it lives in the schema, so it holds on every connection, not only the app's. SQLite gives
-- NEW.id as -1 when the insert names no id, so only a positive id is compared: the app never writes an id below 1.
-- The app's own connection also turns recursive_triggers on (aoi/data/db.py), so REPLACE meets audit_no_delete there.
-- These triggers protect entries from the app's own writes and from SQL mistakes, not from someone who can write
-- aoi.sqlite with another tool: such a person can drop the triggers (docs/security/threat-model.md, the disk gap).

CREATE TRIGGER audit_no_replace BEFORE INSERT ON audit WHEN EXISTS (SELECT 1 FROM audit WHERE uuid = NEW.uuid)
    OR (NEW.id > 0 AND EXISTS (SELECT 1 FROM audit WHERE id = NEW.id)) BEGIN
    SELECT RAISE(ABORT, 'audit entries are never changed'); END;
