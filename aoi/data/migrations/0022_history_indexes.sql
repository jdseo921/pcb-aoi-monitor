-- REQ-LOG-001 (S51): Logs & Export filters 100,000 records within 1 s. One index per filter, each ending in the time,
-- so a filter on one of them reads only its rows of those days; the defect count each listed record shows, and the
-- delete of a record (REQ-LOG-003), find its defects by index instead of reading every defect.
CREATE INDEX inspections_time ON inspections(time);
CREATE INDEX inspections_board_model ON inspections(board_model, time);
CREATE INDEX inspections_operator ON inspections(operator, time);
CREATE INDEX inspections_result ON inspections(result, time);
CREATE INDEX defects_inspection ON defects(inspection_id);
