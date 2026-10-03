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
After the message a window asks for another workspace folder: the folder you choose is opened, then saved in
`settings.json`, in the default workspace folder, as the Settings page saves it (if that folder cannot be written, the
next start asks again); Cancel closes the app. The refused folder is left as it is. The same window follows AOI-SET-011:
the workspace folder cannot be created or opened (a USB or network drive that is not connected) or its `aoi.sqlite` is
not a database the app can open or write (restore the backup, as above); and AOI-SET-012: another program holds
`aoi.sqlite` (another copy of the app, a database tool): close it, then choose the same folder.

**Settings the app cannot read.** A `settings.json` that is not valid JSON, not UTF-8 text or not a JSON object stops
the start with AOI-SET-010, naming the file and, for JSON, the line and column; correct it, or rename it to start with
the default settings. An error at start-up that has no code of its own shows AOI-SET-007; its details are written to
the log in the default workspace folder (`logs/aoi-<date>.jsonl`, event `app.start_failed`) for support.

**Settings and settings.json.** A workspace folder saved on the Settings page is used from the next start; until
then the app keeps the open workspace, its database, log and folders. The AI device, the default epochs and input
size and the log retention apply at once: training and inspection use a new AI device from the next run (a training run
in progress finishes on the device it started with, and the Training page shows the device in use; an inspection run in
progress takes the new device from its next board once the Inspection page is shown again), the Training page's Epochs
and Network input size boxes take the new defaults, and the Logs & Export archive button shows and archives by the new
log retention. The language is stored for the localisation planned for 2H 2027; until then the app shows English. The folder must be a full path
(`C:\AOI_Workspace`, not `AOI_Workspace`): an empty or relative folder, or a log retention, input size or epoch count
below 1, is refused with AOI-SET-008, on the page before anything is saved and at start-up from `settings.json`. The
app writes only the settings it changes into `settings.json`, so a line you edit there while the app runs, such as an
image limit, stays; it takes effect at the next start. Saving needs the Admin role (AOI-USR-001) and writes an audit
entry, `settings.change`, with the values before and after. The last user with the Admin role cannot lose it
(AOI-USR-002): give another user the Admin role first. A user's role is the one set under Users & roles, at every
start too: the app starts with the Admin added first while the workspace has no board model, and with
`operator` after that, so a role you change holds after a restart.

(to be written: the workspace folder, device, limits, demo workspace)

## 2. Board models and scale

**Names.** A new board model's name must differ from every existing one in more than upper and lower case: `tbox-a1`
next to `TBOX-A1` is refused with AOI-TRN-005, since Windows would store the AI model and golden board files of both as
the same files.

Until a board model exists, Home, Inspection, Training, AI Model Test and Recipe Editor say so and offer
**+ New board model**, which an Engineer or Admin uses; an Operator is told to ask an Engineer.

(to be written: creating a board model in full, calibrating px per mm)

## 3. Samples, labels and datasets

**Set Reference** makes the selected OK sample the reference image: inspections compare against it at once, and the
next training run aligns the boards to it before it learns a new golden board. An NG sample is refused (AOI-TRN-006),
and the sample that is the reference cannot be relabelled NG or removed until another OK sample is set (AOI-TRN-007);
with several rows selected, Mark NG and Remove change all the others and leave the reference as it is. Remove asks
first, with No as the default: Enter keeps the samples.

**Importing images** with + OK or + NG is all or nothing: if one picked file cannot be copied (gone, unreadable, or
the workspace drive full), AOI-TRN-008 names it and none of the picked images is imported, so importing them again adds
each once. **Import Folder** imports one image at a time, so Cancel keeps what was imported: a file it cannot copy stops
it with AOI-TRN-009, which says how many images before it were imported. They are in the sample table; importing the
folder again would add them a second time, so import the rest with + OK or + NG, or remove those first.

(to be written: import, OK/NG/UNSURE labels, defect boxes, second-person check, freezing a dataset version,
locking the validation set)

## 4. Training and AI model versions

**A model that cannot judge.** When training gives an AI model that cannot judge boards, for example an image threshold
of 0 because the OK images are copies of one photo, it stops with AOI-TRN-004: nothing is saved and the active AI model
stays in use. Import photos of several different good boards, then train again.

**Stop** ends a training run without saving anything: no AI model version, golden board or audit entry; the active AI
model stays. Closing the app while work runs asks whether to stop it; an AI model test finishes its folder first.

**A run that fails as it is registered** (the disk full, the database held by another program) leaves the Golden board
and the AI model in use as they were, with no new version, file or audit entry; train again once the cause is fixed.
A new version never takes the name of files already in the AI model folder, so no Golden board a result was judged
against is written over.

**Switch User while work runs.** Training, an AI model test, a folder import and the board being inspected finish as the
user who started them, whoever signs in meanwhile: the audit trail and the inspection record name that user, and a
folder import is not refused part-way. An inspection run (Start) stops after that board, and the status bar says so; the
user now signed in presses Start to carry on with the queue, so no board is recorded under a user who did not start it.

(to be written: training, progress and cancel, versions, activation and rollback, the model card)

## 5. Recipes

**A board is never passed on no evidence.** A board model with neither a Golden board nor an AI model, or a recipe
that turns off both "Use the Golden board comparison" and "Use the self-trained AI model", judges nothing: every
board is refused with AOI-INSP-010, which names why each check did not run. A Golden board whose file is gone or
damaged refuses every board of its board model with AOI-INSP-009: put the file back, or choose another OK sample as
the Golden board with Set Reference on Training. Training again does not cure it while the Golden board is one of the
imported samples, since training reads every OK sample. The Recipe Editor and Compare show such a Golden board as one
that cannot be opened, with the file's error code and the same steps, and the app still opens with no error dialog
(#176); an Operator reads the same with "Ask an Engineer". When shown again after Set Reference, a training run, or the
file put back or replaced, both read the Golden board again and show it; Compare then judges the test board it could
not, and the Recipe Editor drops a Try judged against the Golden board before. Until then a test board Compare
was asked to judge shows "Board not inspected" in place of a verdict.

The Selected ROI form edits the ROI selected in the ROI table: Apply and Delete are off while none is, and Delete
leaves none selected. Height and Volume min and max (stored now, checked from Stage 2) are 0 or more, with min not above max; "—",
one step below 0, leaves a limit unset. Apply refuses other values with AOI-RCP-002 and changes nothing.

Each Save Recipe stores a new revision. When a revision was saved after the Recipe Editor loaded its own, for example
with Save to Recipe on Compare, the editor shows it when opened again; if the editor holds changes not yet saved, it asks
first. Choosing No keeps them on screen, but Save Recipe then refuses (AOI-RCP-001) until the newer revision is loaded,
so a save never undoes another without notice. Picking another board model cancels a Try Recipe… still running and
clears the last Try's verdict.

(to be written: drawing ROIs, thresholds, Test Run, revision history, the AOI checklist)

## 6. AI model test and reports

(to be written: running a test, rates with counts and bounds, exports, the validation report)

Each validation run is stored with a UUID and the UUID of the AI model it tested. **Export CSV** writes one row per
image (`image`, `gt` the label, `ai_result` the verdict, `score`, `defects`, `pass_fail`), then `run_uuid`,
`model_version` and `model_uuid`; **Export Report** names the same run and AI model by UUID under the validation folder
those results came from, even when another folder has been picked since to run next. Results stay on the page only
under the board model they were run for: picking another board model in the header clears them, and a run that
ends after such a change is stored but not shown. The report is written whole or not at all and recorded in the
audit trail; when it cannot be written (a folder that cannot be made, a file open in a viewer, a full disk), the
app shows AOI-LOG-002 and an earlier report of that name stays as it was. Selecting a row previews that board; when
it cannot be inspected (its file moved, for example), the preview reads "· Not inspected" with no picture, never the
verdict of the row before.
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
Save to Recipe saves the form's thresholds as a new revision. A stored result is judged again only under its own board
model: with another board model in the header, Re-evaluate refuses with AOI-CMP-005 and names the board model to pick,
and changing the header's board model clears the board of a record from Compare. The thresholds form is loaded again
from the recipe whenever a new revision has been saved since (on Recipe Editor, for example), so Save to Recipe never
puts back the thresholds of an older revision; values tried and not saved stay while no revision is saved. Cancel on
the busy overlay clears the verdict, table and picture and says the board named over the picture was not inspected;
Re-evaluate inspects it. A test image that cannot be read does the same: the banner reads "· Not inspected" and the
pane gives the error's code and what happened. (to be written: trying thresholds, picking another reference)

## 8. Logs and audit

**Export CSV** on Logs & Export writes two files, UTF-8 with a byte-order mark so Excel opens Korean text: the file you
name holds one row per record (id, time, board model, view, AI model version, recipe revision, result, score, defect
count and types, operator, image and overlay paths, then the record's, model's and recipe's UUIDs), and `<name>_checks.csv`
beside it holds one row per check that decided each verdict: the record's time, board model, view, model version and
recipe revision with their UUIDs, then the check's number, region (the whole board, or an ROI's name and box), metric,
source, value, threshold, rule and result. Records from before the checks were stored have no rows in the second file.
Each export is confirmed first and written whole or not at all, and the audit trail records it: a file or folder inside
the workspace, such as the suggested `exports` folder, relative to the workspace (`exports/inspections.csv`), so the
entry still holds after the workspace folder moves; a folder outside it, such as a USB drive, with its full path. If
that entry cannot be written, the exported file is removed (never the station's own file, when exported onto itself).
When a `<name>_checks.csv` is already there, the app asks whether to replace it, with No as the default: Enter keeps it.
**Export Image Overlays** that stops part-way (the drive full or pulled out, a folder already named like an overlay)
shows AOI-LOG-001 with how many images were copied, and the audit trail records those, with the file that failed.

The **From** and **To** boxes take days from 2000-01-01 to 2100-12-31. The picture beside the table is the selected
record's overlay; it is empty when the record's overlay file is gone, when no row is selected and after **Filter**.
When no record matches, the table offers **Reset Filters** (the last 7 days, every board model and operator, archived
records hidden); when every record is older than that or archived, it offers **Show All Records** instead, which sets
**From** to the oldest record's date, **To** to today and ticks **Include archived** when any record is archived.

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
