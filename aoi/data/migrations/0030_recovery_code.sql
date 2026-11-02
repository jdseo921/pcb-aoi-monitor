-- REQ-USR-005 (ADR 0002, decision 6): the first Admin's one-time recovery code, kept only as the Argon2id hash of its
-- letters and digits, never the code; NULL for every other user, and dropped with their password at a reset. A code
-- used is replaced by a new one.

ALTER TABLE users ADD COLUMN recovery_hash TEXT;
