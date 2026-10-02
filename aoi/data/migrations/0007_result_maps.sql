-- REQ-INSP-012 (S25c): the difference map (8-bit PNG, exact) and the AI score map (16-bit PNG, 0.001 sigma steps) of a
-- result are stored beside its overlay and named here; NULL before this migration, and again once the OK sweep ran.
ALTER TABLE inspections ADD COLUMN diff_map_path TEXT;
ALTER TABLE inspections ADD COLUMN ai_map_path TEXT;
