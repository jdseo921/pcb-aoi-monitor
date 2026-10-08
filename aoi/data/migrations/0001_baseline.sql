-- Schema v1: the tables v0.1 stores, unchanged (ADR 0004). Later stages add their own numbered migration.
-- Every statement ends with ';' at the end of a line; a migration never manages its own transaction.

CREATE TABLE users (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('Operator','Engineer','Admin'))
);
CREATE TABLE board_models (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    reference_image TEXT,               -- golden sample used by Compare
    created_at TEXT NOT NULL
);
CREATE TABLE samples (                  -- uploaded training / validation images
    id INTEGER PRIMARY KEY,
    board_model TEXT NOT NULL,
    path TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('OK','NG')),
    defect_type TEXT,                   -- from aoi.defects when label = NG
    side TEXT DEFAULT 'Top',            -- Top | Side | Bottom
    added_at TEXT NOT NULL
);
CREATE TABLE models (                   -- trained model registry (version control)
    id INTEGER PRIMARY KEY,
    board_model TEXT NOT NULL,
    version TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metrics TEXT,                       -- JSON: loss, calibrated thresholds, val scores
    active INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY,
    board_model TEXT NOT NULL,
    revision INTEGER NOT NULL,
    body TEXT NOT NULL,                 -- JSON (aoi.core.recipe.Recipe)
    user TEXT, created_at TEXT NOT NULL
);
CREATE TABLE inspections (
    id INTEGER PRIMARY KEY,
    time TEXT NOT NULL,
    board_model TEXT, model_version TEXT, recipe_rev INTEGER,
    image_path TEXT, overlay_path TEXT,
    result TEXT NOT NULL,               -- OK | NG | WARN
    score REAL, metrics TEXT, operator TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE defects (
    id INTEGER PRIMARY KEY,
    inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    no INTEGER, type TEXT, score REAL, side TEXT,
    x INTEGER, y INTEGER, w INTEGER, h INTEGER
);
CREATE TABLE test_runs (                -- AI Model Test screen history
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, board_model TEXT,
    model_version TEXT, folder TEXT, metrics TEXT, results TEXT
);
CREATE TABLE alarms (
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, level TEXT, message TEXT
);
