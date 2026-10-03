# Engineer manual (draft)

For the engineer who sets up board models, recipes, datasets and AI models. Each section is filled in by the
stage that delivers the feature (Engineering, "Docs as code"). Admin tasks (users, deletion, support bundle)
get their own chapter at release 1.0.

## 1. Workspace and settings

**Upgrades and rollback.** When a new version of the app changes the database, it first copies the workspace database
beside it, in the workspace folder, as `aoi.sqlite.bak-<from>-to-<to>-<UTC time>`, for example
`aoi.sqlite.bak-0004-to-0009-20261002T051500Z`: the database's schema version before and after, and when the copy was
made. If the copy cannot be made (the disk is full, the folder cannot be written) the app stops with AOI-SET-009 and
changes nothing. To roll back, close the app and copy the backup over `aoi.sqlite`; if `aoi.sqlite-wal` or
`aoi.sqlite-shm` are there (after a crash), delete them, since they belong to the replaced file. Then start the version
you upgraded from: this one would upgrade the database again. Results recorded since the upgrade are only in the
replaced file, so keep a copy of it if they matter. The app never deletes the backups; remove old ones by hand.

**A workspace the app refuses.** A workspace created by version 0.1 (AOI-SET-001), written by a newer version
(AOI-SET-002), recorded with a migration file that has changed since (AOI-SET-003), or on a drive without the
database's write-ahead log, such as a network drive (AOI-SET-005), is refused at start-up, before the main window opens.
After the message a window asks for another workspace folder: the folder you choose is saved in `settings.json`, in the
default workspace folder, as the Settings page saves it, and opened; Cancel closes the app. The refused folder is left
as it is. The same window follows AOI-SET-011: the workspace folder cannot be created or opened (a USB or network drive
that is not connected) or its `aoi.sqlite` is not a database the app can open (restore the backup, as above).

**Settings the app cannot read.** A `settings.json` that is not valid JSON, not UTF-8 text or not a JSON object stops
the start with AOI-SET-010, naming the file and, for JSON, the line and column; correct it, or rename it to start with
the default settings. An error at start-up that has no code of its own shows AOI-SET-007; its details are written to
the log in the default workspace folder (`logs/aoi-<date>.jsonl`, event `app.start_failed`) for support.

(to be written: the workspace folder, device, limits, demo workspace)

## 2. Board models and scale

**Names.** A new board model's name must differ from every existing one in more than upper and lower case: `tbox-a1`
next to `TBOX-A1` is refused with AOI-TRN-005, since Windows would store the AI model and golden board files of both as
the same files.

(to be written: creating a board model, calibrating px per mm)

## 3. Samples, labels and datasets

**Set Reference** makes the selected OK sample the reference image: inspections compare against it at once, and the
next training run aligns the boards to it before it learns a new golden board. An NG sample is refused (AOI-TRN-006).

(to be written: import, OK/NG/UNSURE labels, defect boxes, second-person check, freezing a dataset version,
locking the validation set)

## 4. Training and AI model versions

**A model that cannot judge.** When training gives an AI model that cannot judge boards, for example an image threshold
of 0 because the OK images are copies of one photo, it stops with AOI-TRN-004: nothing is saved and the active AI model
stays in use. Import photos of several different good boards, then train again.

(to be written: training, progress and cancel, versions, activation and rollback, the model card)

## 5. Recipes

(to be written: ROIs, thresholds, Test Run, revisions, the AOI checklist)

## 6. AI model test and reports

(to be written: running a test, rates with counts and bounds, exports, the validation report)

Each validation run is stored with a UUID and the UUID of the AI model it tested. **Export CSV** writes one row per
image (`image`, `gt` the label, `ai_result` the verdict, `score`, `defects`, `pass_fail`), then `run_uuid`,
`model_version` and `model_uuid`; **Export Report** names the same run and AI model by UUID under the validation folder.
A folder inside the workspace is stored relative to it, so a moved workspace still finds the run's folder and images; a
folder elsewhere is stored as its full path.

## 7. Compare

Opened from Inspection, or with Use Last Inspected, Compare shows the stored result as it was decided: the table's
thresholds are the ones that applied then, and the line under the verdict names the AI model version and recipe
revision that judged it and what the board model has moved to since. The Golden board pane shows the golden board
the result was judged against, named over the pane: each record keeps that file's path and the SHA-256 of the bytes
the engine read, and the pane gives the reason instead when the file has changed, cannot be read or is gone, or none
was recorded. Re-evaluate inspects the board again with the form's thresholds and the current AI model, against
that same golden board while it is shown (press Golden Board for today's), and shows that fresh result instead;
Save to Recipe saves the form's thresholds as a new revision. (to be written: trying thresholds, picking another reference)

## 8. Logs and audit

**Export CSV** on Logs & Export writes two files, UTF-8 with a byte-order mark so Excel opens Korean text: the file you
name holds one row per record (id, time, board model, view, AI model version, recipe revision, result, score, defect
count and types, operator, image and overlay paths, then the record's, model's and recipe's UUIDs), and `<name>_checks.csv`
beside it holds one row per check that decided each verdict: the record's time, board model, view, model version and
recipe revision with their UUIDs, then the check's number, region (the whole board, or an ROI's name and box), metric,
source, value, threshold, rule and result. Records from before the checks were stored have no rows in the second file.
Each export is confirmed first and written whole or not at all, and the audit trail records it.

**Evidence files.** Beside each record's overlay picture (the results folder, by day) the app keeps the two maps the
verdict was judged on as PNG files named after the overlay: `<overlay name>_diff.png`, the colour difference against the
golden board, and `<overlay name>_ai2.png`, the AI score map in steps of 0.001 σ up to 32.767 σ and of 1/8192 of the
value above (`<overlay name>_ai.png` for results stored before this version, in 0.001 σ steps up to 65.535 σ). A map
file another program holds open, or a damaged one, shows error AOI-CMP-003 on Compare; the stored verdict and decision
table still stand. The maps of OK results are deleted at start-up once older than `map_retention_days_ok` days (7, set
in `settings.json` in the default workspace folder; 0 deletes them at the next start); NG and WARN maps, and every
record, overlay and check, are kept. Each sweep is in the audit trail as `maps.sweep`; a file the app cannot delete
(open in another program) is tried again at the next start.

(to be written: history, archive, the audit trail, error codes)
