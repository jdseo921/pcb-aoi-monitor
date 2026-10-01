-- REQ-SET-017: every record that can leave the station carries a UUID4 beside its local integer key (ADR 0004).
-- SQLite cannot add a UNIQUE column in place, so each column is added and then given a unique index. Rows that
-- exist already (none ship: schema v1 workspaces are development-only) get a random UUID4 so the rule holds.

ALTER TABLE users ADD COLUMN uuid TEXT;
ALTER TABLE samples ADD COLUMN uuid TEXT;
ALTER TABLE models ADD COLUMN uuid TEXT;
ALTER TABLE recipes ADD COLUMN uuid TEXT;
ALTER TABLE inspections ADD COLUMN uuid TEXT;

UPDATE users SET uuid = lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    WHERE uuid IS NULL;
UPDATE samples SET uuid = lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    WHERE uuid IS NULL;
UPDATE models SET uuid = lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    WHERE uuid IS NULL;
UPDATE recipes SET uuid = lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    WHERE uuid IS NULL;
UPDATE inspections SET uuid = lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2)
    || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))
    WHERE uuid IS NULL;

CREATE UNIQUE INDEX users_uuid ON users(uuid);
CREATE UNIQUE INDEX samples_uuid ON samples(uuid);
CREATE UNIQUE INDEX models_uuid ON models(uuid);
CREATE UNIQUE INDEX recipes_uuid ON recipes(uuid);
CREATE UNIQUE INDEX inspections_uuid ON inspections(uuid);
