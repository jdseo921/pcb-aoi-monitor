-- REQ-INSP-008, REQ-INSP-012: every stored result carries its evidence. `result_json` holds the whole result
-- (verdict, score, checks, defects, compare metrics and regions, notes, view, elapsed time) as `InspectionResult.to_dict`
-- writes it; `model_uuid` and `recipe_uuid` name the AI model version and the recipe revision that decided it; and
-- `checks` holds one row per decision variable (region, metric, value, threshold, rule, result), so a verdict can be
-- read and exported check by check. Rows from before this migration keep NULL and no checks: their thresholds were
-- never stored, so none are invented.
ALTER TABLE inspections ADD COLUMN model_uuid TEXT;
ALTER TABLE inspections ADD COLUMN recipe_uuid TEXT;
ALTER TABLE inspections ADD COLUMN result_json TEXT;
CREATE TABLE checks (
    id INTEGER PRIMARY KEY,
    inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    no INTEGER NOT NULL,                -- the check's place in the result, from 1
    region TEXT NOT NULL,               -- 'Board', or the ROI's name and box, e.g. 'R1 @ 110,110 110x110'
    metric TEXT NOT NULL,               -- the check's name, e.g. 'AI anomaly score'
    source TEXT,                        -- AI | Compare | ROI
    value REAL NOT NULL,
    threshold REAL NOT NULL,
    rule TEXT NOT NULL,                 -- how value and threshold decide, e.g. '≥ thr → NG'
    result TEXT NOT NULL,               -- OK | WARN | NG | INFO
    explain TEXT
);
CREATE INDEX checks_inspection ON checks(inspection_id);
