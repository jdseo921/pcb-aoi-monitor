-- REQ-RCP-006 (S29): the board model's scale in px per mm of the board, measured by an Engineer on its Golden board
-- (Calibrate Scale... on the Recipe Editor): a finite REAL above 0, or NULL: its recipe's sizes in px judge as before.
ALTER TABLE board_models ADD COLUMN px_per_mm REAL CHECK (px_per_mm IS NULL OR (typeof(px_per_mm) = 'real' AND px_per_mm > 0 AND px_per_mm <= 1.7976931348623157e308));
