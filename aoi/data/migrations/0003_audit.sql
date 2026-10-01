-- REQ-LOG-004 (audit part): an append-only audit trail (ADR 0004; Engineering standard, "Audit trail").
-- Who changed what, when, with the record before and after. Triggers refuse UPDATE and DELETE, so no screen,
-- service or ad-hoc SQL can edit an entry; a mistake is corrected by a new entry with a reason.

CREATE TABLE audit (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    at_utc TEXT NOT NULL,
    user_uuid TEXT,
    role TEXT,
    action TEXT NOT NULL,               -- recipe.save, threshold.change, model.activate, user.change, export ...
    object_type TEXT NOT NULL,          -- recipe, model, user, inspection, dataset ...
    object_uuid TEXT,
    before_json TEXT,
    after_json TEXT,
    reason TEXT
);
CREATE INDEX audit_object ON audit(object_type, object_uuid);
CREATE INDEX audit_at ON audit(at_utc);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit entries are never changed'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit entries are never deleted'); END;
