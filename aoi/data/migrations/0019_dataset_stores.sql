-- REQ-TRN-017 (S38, ADR 0010): each customer's dataset store, encrypted at rest under a key of its own that Windows
-- Credential Manager keeps, never this database. A board model joins one store and never leaves it; a shredded store's
-- key is deleted and its files with it. Rows never change.

CREATE TABLE dataset_stores (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    customer TEXT NOT NULL,             -- one store a customer while it is not shredded (AppContext.create_store)
    key_id TEXT NOT NULL UNIQUE,        -- hex of the 16 bytes every file's header names
    check_value TEXT NOT NULL,          -- HMAC-SHA-256 of a fixed text under the key: tells a wrong key
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE board_model_stores (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    board_model TEXT NOT NULL UNIQUE,   -- in one store only
    store_uuid TEXT NOT NULL,
    set_by TEXT NOT NULL,
    set_at TEXT NOT NULL
);
CREATE TABLE store_shreds (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    store_uuid TEXT NOT NULL UNIQUE,
    key_id TEXT NOT NULL,
    files INTEGER NOT NULL,             -- the files its board models held when the key was deleted
    shredded_by TEXT NOT NULL,
    shredded_at TEXT NOT NULL
);
CREATE INDEX board_model_stores_by_store ON board_model_stores(store_uuid);
CREATE TRIGGER dataset_stores_no_update BEFORE UPDATE ON dataset_stores BEGIN
    SELECT RAISE(ABORT, 'a dataset store is never changed'); END;
CREATE TRIGGER dataset_stores_no_delete BEFORE DELETE ON dataset_stores BEGIN
    SELECT RAISE(ABORT, 'a dataset store is shredded, never deleted'); END;
CREATE TRIGGER board_model_stores_no_update BEFORE UPDATE ON board_model_stores BEGIN
    SELECT RAISE(ABORT, 'a board model never leaves its store'); END;
CREATE TRIGGER board_model_stores_no_delete BEFORE DELETE ON board_model_stores BEGIN
    SELECT RAISE(ABORT, 'a board model never leaves its store'); END;
CREATE TRIGGER store_shreds_no_update BEFORE UPDATE ON store_shreds BEGIN
    SELECT RAISE(ABORT, 'a shred is never changed'); END;
CREATE TRIGGER store_shreds_no_delete BEFORE DELETE ON store_shreds BEGIN
    SELECT RAISE(ABORT, 'a shred is never undone'); END;
