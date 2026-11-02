-- REQ-USR-005 (ADR 0002, decision 6): the first Admin's one-time recovery code, kept only as the Argon2id hash of its
-- letters and digits, never the code; NULL for every other user, dropped at a reset or a move off the Admin role.

ALTER TABLE users ADD COLUMN recovery_hash TEXT;
