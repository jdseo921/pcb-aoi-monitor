# Engineer manual (draft)

For the engineer who sets up board models, recipes, datasets and AI models. Each section is filled in by the
stage that delivers the feature (Engineering, "Docs as code"). Admin tasks (users, deletion, support bundle)
get their own chapter at release 1.0.

## 1. Workspace and settings

(to be written: the workspace folder, device, limits, demo workspace)

## 2. Board models and scale

(to be written: creating a board model, calibrating px per mm)

## 3. Samples, labels and datasets

(to be written: import, OK/NG/UNSURE labels, defect boxes, second-person check, freezing a dataset version,
locking the validation set)

## 4. Training and AI model versions

(to be written: training, progress and cancel, versions, activation and rollback, the model card)

## 5. Recipes

(to be written: ROIs, thresholds, Test Run, revisions, the AOI checklist)

## 6. AI model test and reports

(to be written: running a test, rates with counts and bounds, exports, the validation report)

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
golden board, and `<overlay name>_ai.png`, the AI score map in 0.001 σ steps. The maps of OK results are deleted at
start-up once older than `map_retention_days_ok` days (7, set in `settings.json` in the default workspace folder; 0
deletes them at the next start); NG and WARN maps, and every record, overlay and check, are kept. Each sweep is in the
audit trail as `maps.sweep`; a file the app cannot delete (open in another program) is tried again at the next start.

(to be written: history, archive, the audit trail, error codes)
