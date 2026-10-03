-- REQ-SET-005 (#198): an alarm whose message is a phrase (an NG verdict, an error shown) stores it as JSON, its English
-- template, translation context and values, so the alarm list shows it in the UI language of the day it is read; the
-- message column keeps the English text for the log and an export. NULL before this migration, and for an alarm a
-- page wrote in the UI language of its moment.
ALTER TABLE alarms ADD COLUMN phrase TEXT;
