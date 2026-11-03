-- REQ-USR-002, REQ-USR-007 (ADR 0002, decision 7): a user is a UUID, name, role, password or PIN hash, status,
-- failed-attempt count and lock time, and nothing else. secret_hash is the Argon2id hash of an Engineer's or Admin's
-- password, or of an Operator's PIN, never the secret. status is 'setup' for an Engineer or Admin who has no password
-- yet, who chooses one at their next sign-in; 'active'; or 'disabled', who cannot sign in and keeps their name on past
-- records (REQ-USR-006). failed_attempts and locked_until (UTC ISO 8601) are the lockout's (REQ-USR-004).

ALTER TABLE users ADD COLUMN secret_hash TEXT;
ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('setup','active','disabled'));
ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until TEXT;
UPDATE users SET status = 'setup' WHERE role IN ('Engineer','Admin');
