-- REQ-INSP-013: an NG or WARN board's review on the line, Real defect (DEFECT) or False call (FALSE_CALL), with who
-- reviewed it, when (UTC) and why. The verdict the board was given stays in `result`, unchanged; every review, and
-- every change of one, is an audit entry (action inspection.review) with the review before and after. NULL for a
-- board not reviewed. The index counts a board model's false calls for Home without reading every record.

ALTER TABLE inspections ADD COLUMN review TEXT;
ALTER TABLE inspections ADD COLUMN review_reason TEXT;
ALTER TABLE inspections ADD COLUMN review_by TEXT;
ALTER TABLE inspections ADD COLUMN review_time TEXT;
CREATE INDEX inspections_review ON inspections(board_model, review);
