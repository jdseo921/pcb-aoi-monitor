-- REQ-INSP-006: every alarm carries an error code beside its UTC time, level and message.
ALTER TABLE alarms ADD COLUMN code TEXT;
