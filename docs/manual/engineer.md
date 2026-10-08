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

(to be written: the decision table, trying thresholds, saving to the recipe)

## 8. Logs and audit

**Export CSV** on Logs & Export writes two files, UTF-8 with a byte-order mark so Excel opens Korean text: the file you
name holds one row per record (id, time, board model, view, AI model version, recipe revision, result, score, defect
count and types, operator, image and overlay paths, then the record's, model's and recipe's UUIDs), and `<name>_checks.csv`
beside it holds one row per check that decided each verdict: the record's time, board model, view, model version and
recipe revision with their UUIDs, then the check's number, region (the whole board, or an ROI's name and box), metric,
source, value, threshold, rule and result. Records from before the checks were stored have no rows in the second file.
Each export is confirmed first and written whole or not at all, and the audit trail records it.

(to be written: history, archive, the audit trail, error codes)
