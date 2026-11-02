# Station metrics: heartbeat and alerts (REQ-SET-024)

The app writes two files that the company's monitoring tools may read while it runs. Neither holds an image, a person's
name or a secret. Times are UTC, ISO 8601 with an offset.

## `heartbeat.json` (workspace folder)

Rewritten whole every 60 s (`aoi/core/heartbeat.py`, `AppContext.heartbeat`), through a temporary file and a rename,
so a reader never sees half of it. A file older than about two minutes means the app is not running, or hangs.

| Field | Meaning |
|---|---|
| `time` | When this beat was written |
| `pid` | The app's process ID |
| `app_version` | The version, with `+build.<n>` in a CI build (REQ-SET-023) |
| `uptime_s` | Seconds since this run opened the workspace |
| `last_inspection` | The last board this run saved: `time`, `board_model`, `ai_model` (the active AI model's version), `recipe_rev`; `null` before the first |
| `last_hour.boards` | Boards saved in the last hour by this run |
| `last_hour.ng` | Of those, boards judged NG |
| `last_hour.verdict_ms_mean`, `last_hour.verdict_ms_p95` | Mean and 95th percentile of their time to a verdict, in ms; `null` with no board |
| `last_hour.false_calls` | Boards reviewed as a False call in the last hour (REQ-INSP-013), by any run |
| `free_bytes` | Free bytes on the workspace's drive; `null` when the system cannot say |
| `wal_bytes` | Size of the database's write-ahead log, `aoi.sqlite-wal`; 0 when there is none |

## `logs/alerts.jsonl`

One line per alarm, appended as it is raised: `time`, `level` (NG, WARN or ERROR), `code` (an `AOI-…` code from
`docs/error-codes.md`, or `null`) and `text`, the alarm's English text. Tail it; the file is not rotated.

## Start-up self-check

At each start, on the heartbeat's thread, `AppContext.self_check` runs SQLite's `PRAGMA quick_check`, reads each
unshredded dataset store's key from this station's key store, counts the files records name that are missing, the
temp files a crash left that could not be removed and the migration backups, and measures the free space. Each failure
raises one alarm, so it is also a line in `alerts.jsonl`: AOI-SET-020 (database), AOI-SET-021 (a store's key, one per
store), AOI-SET-022 (missing files), AOI-SET-023 (temp files left), and AOI-LOG-005 or -006 for the drive. The log
line `self_check.done` holds the counts, and `failed` names a check that could not run (a busy database, say),
logged as `self_check.step_failed`; the other checks still run. The input and output folders are checked once they exist (PRs E.2, E.3).

## Clean exit

`app.close` is logged on every clean exit. While the app runs the workspace holds `aoi.running`; a start that finds it
logs `app.not_closed_cleanly`, as after a kill, a crash or a power cut.
