# ADR 0004: Schema v1, numbered migrations, and the rules for records and writes

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-01
- Decides: the product owner (Jay), until a tech lead joins
- Related: #2, stages S09 to S11 of the Stage 1 plan; REQ-SET-016, REQ-SET-017, REQ-SET-001, REQ-INSP-008;
  Engineering standard "Data and storage"; [ADR 0001](0001-build-on-v0.1.md) (v0.1 workspaces are not upgraded)

## Context

v0.1 creates its tables with `CREATE TABLE IF NOT EXISTS` at every start, so no workspace records which schema
it has and no table that exists can be changed. Records carry integer keys only, times are local without an
offset, and image, overlay and model paths are absolute, so a workspace cannot move and a record cannot be told
apart from another station's. File writes are not crash-safe. Together these are known gap #2.

## Decision

1. **Schema v1 is the baseline migration** `aoi/data/migrations/0001_baseline.sql`: the v0.1 tables as they are
   (`users`, `board_models`, `samples`, `models`, `recipes`, `inspections`, `defects`, `test_runs`, `alarms`).
   Later stages change the schema only by adding a migration.
2. **Migrations** live in `aoi/data/migrations/` as `NNNN_name.sql`, numbered 1, 2, 3 ... without gaps, every
   statement ending with `;` at the end of a line. A file never manages its own transaction and, once shipped, is
   never edited; a mistake is corrected by the next number. `.gitattributes` keeps them LF so the checksum is the
   same on every platform.
3. **The runner** `aoi/data/migrate.py` applies the pending files in order at start-up, each in its own transaction,
   and records each in `schema_version` (number, name, applied_at in UTC, SHA-256 of the text). It refuses, changing
   nothing: a recorded checksum that differs from the file, a recorded number this build does not ship (a newer
   build wrote the database), and a database with tables but no `schema_version` (a v0.1 workspace; the user is told
   to choose a new workspace folder, per ADR 0001).
4. **The connection** opens with `PRAGMA journal_mode=WAL`, `synchronous=FULL` and `foreign_keys=ON`. A folder where
   WAL cannot be enabled (a network drive) is refused with a message.
5. **Records (S10).** Every record that can leave the station (inspections, models, recipes, samples, users) carries a
   UUID4 beside its integer key; the integer key stays local to the workspace. Every time is stored as ISO 8601 UTC
   with an offset (`2026-10-01T05:05:00+00:00`) and shown in local time. Image, overlay and model paths are stored
   relative to the workspace and resolved by one function in `aoi/data`.
6. **Writes (S11).** Every file the app writes goes to a temporary name in the same folder, is flushed and fsynced,
   then renamed over the target. A finished inspection is committed, row and files, before the next board starts.

## Alternatives considered

- **Alembic with SQLAlchemy.** One more dependency and an ORM the engine does not need for one SQLite file;
  revisions are tracked by id without a checksum.
- **`PRAGMA user_version`.** One integer: no names, no checksums, no record of when.
- **Upgrading v0.1 workspaces.** They hold synthetic test data only (ADR 0001); an upgrade path would be code that
  no customer runs.
- **Python migrations.** SQL files cover Stage 1. A `.py` migration can join the same numbering if a data
  transformation ever needs code.

## Consequences

- A schema change is a new file plus a test, reviewed as code, and `schema_version` shows what any workspace has.
- A station whose workspace is on a network drive is refused; the workspace folder is local, as the Engineering
  standard asks.
- Downgrading the app is refused; going back means restoring the workspace from its backup.
