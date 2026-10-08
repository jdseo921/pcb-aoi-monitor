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
not a database the app can open or write (restore the backup, as above); and AOI-SET-012: another copy of the app has
the workspace open (on this PC, or in another user's session), or another program holds `aoi.sqlite` (a database
tool): close it, then choose the same folder. A copy of the app that crashed, or a power cut, never blocks the next
start. The workspace folder holds an empty file `.aoi.lock` while the app runs; leave it where it is. If another program
takes hold of `aoi.sqlite` while the app runs, a change that cannot be stored is refused after 5 s with AOI-SET-013:
close that program and do the change again.

**Settings the app cannot read.** A `settings.json` that is not valid JSON, not UTF-8 text or not a JSON object stops
the start with AOI-SET-010, naming the file and, for JSON, the line and column; correct it, or rename it to start with
the default settings. An error at start-up that has no code of its own shows AOI-SET-007; its details are written to
the log in the default workspace folder (`logs/aoi-<date>.jsonl`, event `app.start_failed`) for support. One that
comes once the workspace is open, while the main window is built (a damaged database, for example), shows
AOI-SET-007 too, writes its details to that workspace's log (event `error.shown`, context `start-up`) and closes the
app with the workspace closed; send that log file to support.

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
the same files. It is also the name of the board model's folders in the workspace, so a name with `/` or `\`, one of
`: * ? " < > |`, a dot or space at its end, or a device name such as `CON` or `COM1` is refused with AOI-TRN-019.

Until a board model exists, Home, Inspection, Training, AI Model Test and Recipe Editor say so and offer
**+ New board model**, which an Engineer or Admin uses; an Operator is told to ask an Engineer. Start and Next Board
on Inspection stay grey until a board model is chosen in the top bar, and so does Compare's Save to Recipe, since there
is no recipe for a threshold to differ from; another action that needs one shows AOI-SET-014 (select a board model; an
Engineer or Admin creates the first with **+ New**).

**Scale.** A board model's scale, in px per mm of the board, lets its recipe give sizes in mm, so that a recipe can
survive a camera change (REQ-RCP-006). The scale does not follow the images by itself: after a camera change, or any
other change of image size, set it again on the new Golden board before boards are judged; until then sizes in mm keep
their px at the old scale, as sizes in px always do. With a scale, the Recipe Editor names it above the Golden board,
the ROI table gives X, Y, W and H in mm, and the minimum defect size, on Thresholds and on Compare, is a width in mm
(that of a round defect), with the px it spans beside it; the next Save Recipe stores the sizes in mm, and boards are
judged as before at that scale. Until then, AOI-RCP-009 in amber under the scale counts the sizes the latest revision
still holds in px and says to press Save Recipe: shown in mm, they keep their px when the scale is set again, while
sizes in mm follow it. Save to Recipe on Compare stores a size typed in mm and keeps one left untouched as the recipe
holds it, so AOI-RCP-009 stays after it. Without a scale, sizes stay in px, with AOI-RCP-005 in amber under
Calibrate Scale…, and a recipe saves all the same. A stored scale that cannot be read, AOI-RCP-012, judges and saves
nothing until it is set again.
To set the scale, press **Calibrate Scale…** on the Recipe Editor (it needs the Golden board): click two points on the
Golden board a known distance apart (a third click starts again), or type the length between them in px, enter that
distance in mm and press **Set Scale**; the status bar then names the scale, with AOI-RCP-009 while the latest revision
holds sizes in px. Cancel or Esc closes the sheet with nothing set, and so do another board model, the Golden board
replaced, another user signing in and Try Recipe…; the sheet opens on the Golden board, a Try's verdict gone. Set Scale
on a Golden board replaced while the page is shown, as at a training run's end, sets nothing and says so with
AOI-RCP-008. The audit trail keeps each scale set (board_model.scale) with the length, the distance and the Golden
board it was measured on. Setting the scale again moves a size held in mm to its px at the new scale, while a size
still in px stays as it is, and Inspection judges its next board at it (a run in progress says so with AOI-INSP-013
while its recipe holds a size in mm).

**Smallest defect.** A minimum defect size that spans under 4 px in the board images is too small to tell from
image noise: AOI-RCP-007 shows in amber, on Thresholds under the field with what to do, and on Compare in one line
with the least size, at the top of the "why" box while Try other thresholds shows (REQ-INSP-014). At 4 px or more the
px beside the size carry a ✓. The recipe saves all the same, and the audit entry of its revision keeps the code. After
Set Scale, the status bar says AOI-RCP-007 too while the size spans under 4 px at the new scale, as a size held in mm
can at a smaller scale. When the window is too short for every field of the Thresholds tab, as on a 1600 × 900 screen
with this notice and the note under the AI score threshold shown, the tab scrolls: use the scroll bar at its right,
the mouse wheel, or Tab, which brings each field into view.

(to be written: creating a board model in full)

## 3. Samples, labels and datasets

**Set Reference** makes the selected OK sample the reference image: inspections compare against it at once, and the
next training run aligns the boards to it before it learns a new golden board. An NG sample is refused (AOI-TRN-006),
and the sample that is the reference cannot be relabelled NG or removed until another OK sample is set (AOI-TRN-007);
with several rows selected, Mark NG and Remove change all the others and leave the reference as it is. Remove asks
first, with No as the default: Enter keeps the samples.

**Mark NG…** asks which of the 33 defect types of the defect classification table the selected samples show (a
category narrows the list): none is picked at first, "Unknown" is not offered, and OK stays grey until a type is picked,
so no sample is NG without one (AOI-TRN-013). **Mark OK** clears the type. Neither changes a sample's view.

**Importing images.** **Add OK Images…** (Ctrl+O), **Add NG Images…** (Ctrl+N) and **Import Folder…**
(Ctrl+Shift+O) open the import sheet above the sample table, with the files picked or found in the folder; no dialog
opens over the file picker. Its title names the board model the files go to, the one in the header when it opened;
another one picked there closes the sheet if it has not imported yet. A sheet that has imported, or is importing, stays
with its list: its Import is off and a line names the board model its files are for until that one is back in the
header, and Close (Esc) closes it. A sign-in closes the sheet too; an import that runs then goes on as the user
who started it, and the sheet closes once it ends. A folder with no image
opens no sheet, and the status line says so. A name too long for its cell is cut at its start, so its end shows, and a
screen reader reads its whole path. Import Folder… labels each image by its sub-folders: under `ok/` or `good/` OK,
under `ng/`, `bad/`, `defect/` or `defects/` NG, with the defect type of its folder when that folder is named after one
of the 33 types (`ng/solder_bridge/`, spaces or underscores, any case); an image in neither is "unsorted: pick a label".
An import labels an image OK or NG only, as the user who pressed Import; UNSURE is only ever a later label.
**View** (Top for every new batch) and **Label for all** set every row; **Defect type for NG files** (a category, then a
type with its severity) sets every NG row; a row's own label, type or view is picked in its cell (tap a selected cell,
double-click it or press F2). **Import** (Enter) stays grey until every NG file has one of the 33 types; "Unknown" is
not offered. The files are copied into the workspace one at a time in the background and are never changed where they
are. Each row then says "copied", "not imported", or the code and title of what refused it; the row selected (a tap or
the arrow keys) shows what happened and what to do in a line under the table, as pointing at it does: a file Inspection
would refuse (not an image, cut short, over the size limits: AOI-INSP-001, -004 to -007), an image the board model
already has (the same SHA-256, under any file name or label, and one picked twice: AOI-TRN-015, which names the sample
that has it and its label) or a file with no label (AOI-TRN-016); the others go in. **Copy List** copies every row with
what happened; Import again imports the rest and skips the images already imported. **Cancel** (Esc) while it runs keeps
the images already copied, and the status line says how many OK and NG images that was and into which board model;
once it is done, Cancel or Close
(Esc) closes the sheet. The line beside the buttons counts the NG files that still need a type, and after an import the
files of the sheet imported, already imported and not imported. A file that cannot be copied stops the import with
AOI-TRN-009, and any other error after an image went in with AOI-TRN-010; both say how many images before it were
imported, which stay in the sample table, and which board model to pick in the header before you press Import again.
An error in an import you cancelled opens no message, but it is in the log and
the alarm list. The same goes for an import that stops after its user has signed out: the status line then names the
board model and the file it stopped at; the user who pressed Import, if signed in again by then, gets the message.

**Labels keep their history.** Each image is labelled OK, NG or UNSURE, and an NG image can carry defect boxes, each
with its position and size in whole pixels of the image as it is shown, turned upright as its EXIF Orientation says, one
of the 33 defect types and the severity the defect table gives the type. Mark OK and Mark NG on Training, and every
later label or box change, add a label to the image's history and keep the one before, with its boxes, who labelled it
and when; nothing is deleted, and the audit trail records each change (`sample.update`, `label.set`). Images labelled
before this version keep their label, with no labeller recorded. Marking an image as it is labelled already changes
nothing, unless no labeller is recorded for its label: then it is labelled again, by you, so that a second user can
check it. An UNSURE image is left out of training and its calibration and counted as neither OK nor NG on Training and
Home. A box must lie inside the image (AOI-TRN-031); a label an image cannot take, such as a box on an OK image or a
type not one of the 33, is refused (AOI-TRN-030). No screen marks an image UNSURE, draws boxes or lists UNSURE images
for the customer's quality engineer yet: the label editor comes next.

**A second user checks each label.** The labels of a board model and view are ready to freeze into a dataset only
once a second Engineer or Admin has checked every NG label and OK labels drawn at random, 10 % of them rounded up; the
draw's seed, count and labels are stored and audited, and a draw adds to earlier ones as OK images are added. You cannot
check a label you made (AOI-TRN-033). An NG image needs a defect box before its label is checked, an UNSURE label is
not checked, and a label from before this version, with no labeller, is labelled again first (AOI-TRN-034). A relabel
needs a new check. Until sign-in arrives in version 1.0, the second user is the second name picked in the user list,
which the validation report states. No screen draws or checks labels yet: the services do, and the screen comes later.

**Two labellers agree before a customer validation.** Pick 100 images of the board model, each labelled OK or NG, as a
calibration set. Two Engineers each label every image of the set blind, OK, or NG with one of the 33 defect types, once
per image; no screen hides an image's own label yet, so not looking at it is up to each labeller. The agreement check
then counts the images on which the two agree on OK or NG, at least 98 of 100, and the images both labelled NG on which
they agree on the defect type, at least 90 % (both targets proposed). Every check is stored with its counts, and the
newest one decides whether a dataset version can be frozen. A set that is not 100 such images (AOI-TRN-035), a second
blind label (AOI-TRN-036) and a labeller who has not labelled every image (AOI-TRN-037) are refused. None of this has a
screen yet.

**A frozen dataset version keeps its record.** Freezing takes the OK and NG images of one board model and view, with the
board revision, the customer and the allowed uses (their own AI models by default), as DS-TBOXA1-R3-TOP-v4: the board
model without hyphens, the revision, the view and a number counting per board model and view. It writes
datasets/<name>/manifest.json with each file's path, SHA-256, label, boxes, labeller and checker, and keeps the
manifest's SHA-256. It waits for every NG label (AOI-TRN-020) and the drawn OK labels (AOI-TRN-021) to be checked, a
customer (AOI-TRN-024) and an agreement check that reached its targets (AOI-TRN-027): the newest one of the board model
whose set holds images of the view decides, so a newer check short of the targets stops freezing until a newer one
reaches them. A board model whose name has no Latin letter or digit (AOI-TRN-039), or whose letters and digits name
another board model's versions (AOI-TRN-040), cannot be frozen; import its images under another name. A manifest that
cannot be written is AOI-TRN-041, or AOI-TRN-042 when its path is too long, and nothing of the version is kept. The
version's record and manifest never change, and a later label change goes into the next version. The version names the
workspace's image files rather than copying them; the app never changes or removes one, but a file changed or removed
outside the app cannot be recovered from the workspace, so back the workspace up. Verifying a version hashes its
manifest and every file again and lists each file that changed or is missing since the freeze; train from another
version when one did. No screen freezes or verifies a version yet.

(to be written: the label editor and UNSURE on the Samples tab, the check and the blind labels on screen, the Datasets
tab, locking the validation set)

## 4. Training and AI model versions

**A model that cannot judge.** When training gives an AI model that cannot judge boards, for example an image threshold
of 0 because the OK images are copies of one photo, it stops with AOI-TRN-004: nothing is saved and the active AI model
stays in use. Import photos of several different good boards, then train again.

**An import** runs in the background (#194): the sample table shows "Importing…" after a second, and progress, the
time left and Cancel after ten. While any import runs, Add OK Images…, Add NG Images…, Import Folder… (also the link
in an empty sample table) and Start Training are off, "Importing…" stays over the table when the page is shown again,
and a Switch User does not stop it: the samples are recorded as added by the user who started the import. The line
over the sample table counts the OK and NG samples and names the reference image (under it, while fewer than 20 OK
samples are imported, a tip says that 20 or more give a steadier threshold); a name too long for the line is cut at its
end (…), and pointing at the line shows it whole. If the system refuses the path of a sample's copy in the workspace as
too long (a workspace folder with a long path, on Windows with long paths off), the import keeps the images it
imported before that file and names AOI-TRN-011 in AOI-TRN-010; when that file was the first, it shows AOI-TRN-011
itself, which counts every image it was to import. The steps are those of AOI-INSP-014 (section 8, Evidence files).

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

**Training or activating while boards are inspected.** A new AI model version, an activation or a rollback, a saved
recipe, a scale and a Golden board set with Set Reference apply on the Inspection page from the next board that starts,
with no
need to leave the page: the board in hand finishes with what it started with, and a run in progress goes on with the
new one, saying so under the verdict banner and in the alarm log with AOI-INSP-013. Each record names the AI model
version active when its board was judged, the recipe revision that judged it (which says whether the AI check ran)
and the Golden board it was judged against: the CSV export of Logs & Export lists the AI model version and recipe revision of each board, and Compare
shows a stored board beside the Golden board it was judged against. A run whose recipe turns the AI check off moves only
when the recipe, the scale or the Golden board changes, as no AI model judges its boards: an activation or a rollback
during it
raises no AOI-INSP-013, though the boards after it name the version now active, while a training run still does, as it
sets a new Golden board, and the line names no AI model but says the AI check was off.
A scale set changes nothing that judges a board while the recipe holds its sizes in px, so it then moves no run, with
the AI check on or off.

**Threshold column.** Each AI model version's calibrated AI score threshold, which judges the board model's boards while
the recipe holds no override of its own (section 5). A version whose calibrated value the AI model registry cannot give,
which only a change made by hand leaves, reads AOI-TRN-012, with what happened and what to do as the row's tooltip
and in a line under the table: for the next boards, train again or activate another version, or set a value of your
own for the board model (section 5). Where such a row's sample counts cannot be read either, its OK/NG cell stays
empty.

(to be written: training, progress and cancel, versions, activation and rollback, the model card)

## 5. Recipes

**A board is never passed on no evidence.** A board model with neither a Golden board nor an AI model, or a recipe
that turns off both "Use the Golden board comparison" and "Use the self-trained AI model", judges nothing: every
board is refused with AOI-INSP-010, which names why each check did not run. A Golden board whose file is gone or
damaged refuses every board of its board model with AOI-INSP-009: put the file back, or choose another OK sample as
the Golden board with Set Reference on Training. Training again does not cure it while the Golden board is one of the
imported samples, since training reads every OK sample. The Recipe Editor and Compare show such a Golden board as one
that cannot be opened, with the file's error code and the same steps (a long file name in it wraps onto the next line
after a _ or -), and the app still opens with no error dialog (#176), though the alarm log on Inspection records it
once with that code (#195); an Operator reads the same with "Ask an Engineer". When shown again after Set Reference, a
training run, or the
file put back or replaced, both read the Golden board again and show it; Compare then judges the test board it could
not, and the Recipe Editor drops a Try judged against the Golden board before. Until then a test board Compare
was asked to judge shows "Board not inspected" in place of a verdict.

The Selected ROI form edits the ROI selected in the ROI table: Apply and Delete are off while none is, and Delete
leaves none selected. Its AI score field, "AI score (× AI score threshold)", is the ROI's threshold as a multiple of
the AI score threshold the AI check uses: the recipe's when the recipe sets one, otherwise the AI model's (the
Threshold column on Training). An ROI is NG when the highest AI score inside it reaches that multiple. The Height and
Volume thresholds, min and max (stored now, checked from Stage 2), are 0 or more, with min not above max; "—", one step
below 0, leaves a threshold unset. Apply refuses other values with AOI-RCP-002 and changes nothing.

Each Save Recipe stores a new revision. When a revision was saved after the Recipe Editor loaded its own, for example
with Save to Recipe on Compare, the editor shows it when opened again; if the editor holds changes not yet saved, it asks
first. Choosing No keeps them on screen, but Save Recipe then refuses (AOI-RCP-001) until the newer revision is loaded,
so a save never undoes another without notice. Picking another board model cancels a Try Recipe… still running and
clears the last Try's verdict.

**AI score threshold** (Thresholds tab). Each AI model is calibrated to an AI score threshold when it is trained (the
Threshold column on Training), and the recipe judges by that value unless you override it for the board model. The tick
names the active AI model's value ("Override 3.063"), and the field beside it shows that value greyed until you tick
it. Ticked, the field starts from the value that judges when you tick, even if an AI model was trained or activated
while the page stayed open, and holds yours; Save Recipe keeps it in a new revision. Clear the tick and
save to go back to the calibrated value, which then follows each AI model trained or activated later. Every board
judged after the save uses the same threshold: on Inspection, on Compare (Re-evaluate and boards it inspects) and in AI
Model Test. The audit trail records setting, changing and clearing the override (section 8). With no value to name,
the tick reads "Set my own value", the field shows once ticked, starting from 0, which is no override: type your value
before you save, as a save with 0 keeps none. The note under them says why there is no value to name: no AI model is
trained yet, or no AI model version is active, or, when the AI model registry holds no usable calibration for the
active AI model (only after a change by hand), AOI-TRN-012 with what to do: for the next boards, train again or
activate another version on Training, or set a value of your own.

(to be written: drawing ROIs, the other thresholds, Test Run, revision history, the AOI checklist)

## 6. AI model test and reports

(to be written: running a test, rates with counts and bounds, exports, the validation report)

Each validation run is stored with a UUID and the UUID of the AI model active when it ran. **Export CSV** writes one row
per image (`image`, `gt` the label, `ai_result` the verdict, `score`, `defects`, `pass_fail`, `ai_check`), then
`run_uuid`, `model_version` and `model_uuid`. `ai_check` is `RAN`, `OFF` or `NO_AI_MODEL`, as on Logs & Export: with
`OFF` the recipe turned the AI check off, so the AI model named did not judge the images, and the report says so under
its head. `gt` is OK or NG from the image's sub-folder (`ok/` or `ng/`), or `?` for an image in neither; `pass_fail` is
`PASS` when the verdict (WARN counted as NG) matches the label, `FAIL` when it differs and `NO_LABEL` for an image with
no label, shown in the table and the report's Matches label? column as Matches label, Differs from label (in red) and No
label. **Export Report** names the same run and AI model by UUID under the validation folder those results came from,
even when another folder has been picked since to run next. Results stay on the page only under the board model they
were run for: picking another board model in the header clears them, and a run that ends after such a change is stored
but not shown. The report is written whole or not at all and recorded in the audit trail; when it cannot be written (a
folder that cannot be made, a file open in a viewer, a full disk), the app shows AOI-LOG-002 and an earlier report of
that name stays as it was. Selecting a row previews that board; when it cannot be inspected (its file moved, for
example), the preview reads "· Not inspected" with no picture, never the verdict of the row before. A preview is judged
by the recipe revision, Golden board and scale that judged the run and, when that recipe ran the AI check, its AI model.
Once another is in use (training ended, a version was activated, a recipe saved, a scale or a Golden board set), a
selected row
is not previewed: the pane reads "Not inspected" with AOI-TST-001 (a long file name in it wraps onto the next line after
a _ or -), and Compare's Use Last Inspected keeps the board it had. A line above the table then names what judged the
run and what is in use now; it shows when the page is opened or a row is selected, so after a training run that ends
while the page stays open it appears at the next row selected. When the page is opened, a row still selected from before
shows the same in place of its earlier preview; once what judged the run is in use again (that AI model version
activated again, for example), it is previewed again. A run judged with the AI check off was judged by no AI model, so
activating another AI model version leaves its rows previewed; a saved recipe, a Golden board set or a training run,
which sets a new Golden board, still stops their previews. A scale set stops no preview of a run whose recipe holds its
sizes in px, which no scale changes. The line and AOI-TST-001 then name "no AI model (the AI check
off)" for that run, and for a recipe now in use that turns the AI check off, in place of an AI model. The rows and both
exports still describe the stored run; press **Run Test Again** in the preview pane to test the run's folder with what
is in use now. A preview still being inspected when a new run ends is not shown beside its rows. A folder inside the
workspace is stored relative to it, so a moved workspace still finds the run's folder and images; a folder elsewhere is
stored as its full path.

## 7. Compare

Opened from Inspection, or with Use Last Inspected, Compare shows the stored result as it was decided: the table's
thresholds are the ones that applied then, and the line under the verdict names the AI model version active when the
board was judged and the recipe revision that judged it, and what the board model has moved to since, and for a result
judged at another scale than the board model's now, both scales: Re-evaluate applies sizes in mm at the one it was
judged at, and the form shows them at the board model's (when that
revision turned the AI check off, the "why" box says it did not run). The Golden board pane shows the golden board
the result was judged against, named over the pane: each record keeps that file's path and the SHA-256 of the bytes
the engine read, and the pane gives the reason instead when the file has changed, cannot be read or is gone, or none
was recorded. When a stored map cannot be read (AOI-CMP-003), the heat views show the picture alone; when the stored
board picture cannot be read (AOI-CMP-006), the test pane says "Board picture no longer stored"; either way the
Golden board pane shows the golden board as judged, the verdict and table stand, the dialog names the file, and the
line under the verdict keeps the error's code. When nothing of the result's pictures can be read,
both panes say why, with the message's code (AOI-SET-013 when another program holds the workspace
database), and the Golden board pane what to do; neither pane ever shows the result opened before.
The thresholds form, Re-evaluate and Save to Recipe are in the Try other thresholds panel under the two pictures, for
Engineer and Admin, so the decision table beside the pictures shows all its rows; an Operator does not see it, and
Compare judges an Operator's boards by the board model's recipe, never by values left in the form. Its AI score
threshold works as on the Recipe Editor (section 5), with the tick under the field, reading
"Override the AI model's value 3.063", except that on a stored result the tick
names the calibrated value of the AI model that judged it, which Re-evaluate applies while the tick is clear; on any
other board, and on a stored result judged with the AI check off, it names the active AI model's. On a stored result,
once the load of its pictures and maps has ended, Re-evaluate (Ctrl+R) judges it again
with the form's thresholds from its stored maps and the calibration of the AI model that judged it, without running the
AI model: the banner keeps the stored verdict, "Would be" beside Re-evaluate shows the verdict they give (when that takes
over a second, "Re-evaluating…" covers the table and the explanation meanwhile, Re-evaluate is off until it ends, and
its Cancel keeps the stored checks and puts the focus on Re-evaluate, as does the end of the run while Cancel has it;
pressed from the keyboard, Re-evaluate leaves the focus in the explanation, one Tab before Cancel once that shows, so a
second Space presses nothing, and takes it back at the end; a focus on Re-evaluate waits there too while Re-evaluate is
off for a result's pictures and maps to load, after "Compare with Golden board ›" on Inspection, say, and is back on it
once they have, never on Save to Recipe; an error takes the indicator away with its message), and the table
and the explanation show their checks until you change a threshold, the form takes a revision saved on another page,
you open another result, inspect a board or change the board model, or an Operator signs in on any page. The board
keeps the stored result's defect boxes: when defects make the verdict WARN, the explanation says how many the thresholds
would mark.
Nothing is stored. A result whose map is gone gives AOI-CMP-004, naming it: inspect the board again and try the
thresholds on the new result. Any other board, and a pane's Re-evaluate › on a stored result, is inspected again from
its image file with the form's thresholds and the current AI model, against the golden board as judged while it is shown
(press Golden Board for today's).

Save to Recipe (Ctrl+S, the blue button) is on once a threshold in the form differs from the recipe, even one that did
not judge the board shown, such as the AI score threshold with the AI check off, and off while Re-evaluate runs; an
override the field shows rounded is no change, so a revision never repeats the recipe. It opens a sheet in place of the
panel, not a message box, that lists each threshold that changes, before → after (no override of the recipe's own reads
"the AI model's calibrated value", which the saved revision judges by, while the board model has an active AI model
whose calibration can be read as the sheet opens, else "none"; a value with more decimals than its field shows reads
with all of them), names the revision the save makes and asks for a reason. Save Revision, or Enter in the reason, is on
once a reason is typed: it stores the new revision with your reason, the stored result keeps its verdict, and boards
inspected afterwards are judged by it (on Inspection from the next board, a run in progress included), as the Recipe
Editor shows when opened again. Cancel, or Esc in the sheet, closes it with nothing stored and the values tried kept in
the form; so does opening any board on Compare, the one shown included (a stored result, from Inspection or Last
Inspected, or a file), so a reason typed before never goes with what you open; a record that cannot be opened leaves the
page, the sheet included, as it was. A sign-in closes it too: an Engineer or Admin keeps the values tried, and an
Operator's sign-in puts back the recipe's. A change of board model, or a revision saved elsewhere meanwhile (AOI-RCP-004
says so when Compare shows again, or when you press Save Revision), also closes it, and the form then holds that recipe:
try your values again on it. When the sheet closes, the focus goes back to the panel if it was in the sheet (to the
explanation while a stored result is still loading, Save to Recipe and Re-evaluate both off, and on to Re-evaluate once
it has loaded); moved elsewhere, to the board model in the header say, it stays there. A long board model name in the
sheet's heading wraps after each _ and -; a part with neither stays whole.
With a scale, the sheet lists the minimum defect size in mm, as its field shows it, and a scale set after Compare
showed the recipe closes it as a revision saved elsewhere does (AOI-RCP-010 says so), the form then holding the
recipe at the new scale.

A stored result is judged again only under its own board
model: with another board model in the header, Re-evaluate refuses with AOI-CMP-005 and names the board model to pick,
and changing the header's board model clears the board of a record from Compare. A test image you picked stays,
without the last verdict (an inspection of it still running stops), and is judged under the new board model at
once if Compare is shown, or when you next open Compare: a board that no check can judge there (AOI-INSP-010),
or whose Golden board cannot be opened (AOI-INSP-009), is said on the test pane, with no message box and no
alarm; Re-evaluate shows the message and stores the alarm, which is kept even when you cancel that inspection
or start another. "+ New" with the name of the board model already in the header changes nothing: the status
bar says it is already selected, and a stored result stays as it was. The thresholds form is loaded again
from the recipe whenever a new revision has been saved since (on Recipe Editor, for example), so Save to Recipe never
puts back the thresholds of an older revision; values tried and not saved stay while no revision is saved and no
Operator signs in. When an Operator signs in, on Compare or on any other page, the form goes back to the recipe's
thresholds, which you find there when you sign in again, and a board inspected with values the recipe does not hold at
that sign-in (values you left unsaved, a revision saved since the board was inspected, or a scale set since that gives a
size in mm other px; values that did not judge
the board are not counted: the AI score threshold, and an ROI's AI score and name, when its AI check did not run;
Pixel difference, Similarity minimum and Allowed difference regions when its Golden board comparison did not run; a
disabled ROI; and an ROI's Height and Volume thresholds, not checked before Stage 2) is cleared, even while your
inspection still runs, and inspected again by the recipe once Compare is shown, so the Operator never sees its verdict,
decision table or explanation; a board inspected with the values the recipe then holds keeps its verdict (values you
saved with Save to Recipe after inspecting are the recipe's), an inspection you cancelled stays cancelled, and a stored
result stays as it was decided. Cancel on the busy overlay clears the verdict, table and picture and says the board
named over the picture was not inspected; Re-evaluate inspects it. A test image that cannot be read does the same: the
banner reads "· Not inspected" and the pane gives the error's code and what happened. A long file name over a picture,
in a message on a picture's pane or in the line under the verdict wraps onto the next line after a _ or -. (to be
written: picking another reference)

## 8. Logs and audit

**Recipes in the audit trail.** Each Save Recipe and Save to Recipe is recorded as `recipe.save` with the recipe before
and after, the user and the time; a Save to Recipe also with the reason typed in its sheet.
One that sets, changes or clears the board model's override of the AI score threshold is also recorded as
`recipe.ai_threshold`, naming the board model, the user, the revisions and the value before and after: the override, or
the AI model's calibrated value that judges without one, with that AI model's version.

**Export CSV** on Logs & Export writes two files, UTF-8 with a byte-order mark so Excel opens Korean text: the file you
name holds one row per record (id, time, board model, view, AI model version, recipe revision, result, score, defect
count and types, operator, image and overlay paths, then the record's, model's and recipe's UUIDs and `ai_check`), and
`<name>_checks.csv` beside it holds one row per check that decided each verdict: the record's time, board model, view,
AI model version and recipe revision with their UUIDs and `ai_check`, then the check's number, region (the whole board,
or an ROI's name and box), metric, source, value, threshold, rule and result. `ai_check` says whether the AI check ran
on the record: `RAN`, `OFF` (turned off in the recipe; the AI model version is the one active then, which did not judge
the board) or `NO_AI_MODEL` (none trained), and is empty for a record stored without its result or one whose stored
result cannot be read (damaged), which the log names (`export.result_not_read`) without stopping the export. Records
from before the checks were stored have no rows in the second file.
Each export is confirmed first and written whole or not at all, the two CSV files together, and the audit trail
records it: a file or folder inside the workspace, such as the suggested `exports` folder, relative to the workspace
(`exports/inspections.csv`), so the entry still holds after the workspace folder moves; a folder outside it, such as a USB drive, with its full path. If
that entry cannot be written, the exported file is removed (never the station's own file, when exported onto itself).
A file that cannot be written, such as one still open in Excel, stops the export with AOI-LOG-002, which names it: close
it, or choose another name or folder, and export again; the files already there stay as they were. When a
`<name>_checks.csv` is already there, the app asks whether to replace it, with No as the default: Enter keeps it.
**Export Image Overlays** that stops part-way (the drive full or pulled out, a folder already named like an overlay)
shows AOI-LOG-001 with how many images were copied, and the audit trail records those, with the file that failed.
Both exports run in the background (#194): the window keeps answering, and after a second the table shows
"Exporting…" with the seconds so far, then Cancel. Cancel on **Export Image Overlays** keeps the overlays already copied
and the status line says how many; Cancel on **Export CSV** before its files are written leaves neither file. While
an export runs both export buttons are off, "Exporting…" stays over the table after Filter, and a Switch User does not
stop it: the audit trail names the user who started it. **Save Image…** (F9) on Inspection, which every role may
use, records each picture in the audit trail as `export.image`, with who saved it, the record it shows, its board model,
board file and verdict, and where it went, stored as above. F9 pressed during a run records the board shown when it
was pressed, even if the run moves on while the file is named. A picture goes into place only with its entry: when
the entry cannot be written, the destination is left exactly as it was, a file of that name unchanged and no picture
or new folder left.

The **From** and **To** boxes take days from 2000-01-01 to 2100-12-31. The picture beside the table is the selected
record's overlay; it is empty when the record's overlay file is gone, when no row is selected and after **Filter**.
When no record matches, the table offers **Reset Filters** (the last 7 days, every board model and operator, archived
records hidden); when every record is older than that or archived, it offers **Show All Records** instead, which sets
**From** to the oldest record's date, **To** to today and ticks **Include archived** when any record is archived.

**Evidence files.** Each record's overlay picture is in the results folder, by day, named
`<stem>_<record UUID>_<verdict>.png`: `<stem>` is the first 40 characters of the board's image file name without its
extension, and the UUID is the record's own, as the `uuid` column of the CSV export gives it, so two boards with the
same file name never share a picture. A training sample's copy is named `<stem>_<sample UUID>.<extension>` the same way.
Records and samples stored before this version keep their names. If the system still refuses an evidence file's path as
too long (a workspace folder with a long path, on Windows with long paths off), the run stops with AOI-INSP-014: an
Admin saves a workspace folder with a shorter path on Settings and then, with the app closed, copies everything in the
workspace folder into it (a move takes along settings.json, which names the folder the app opens), or turns on long
paths in Windows; the next start opens the copy and all it holds. Beside the overlay the app keeps the two maps the
verdict was judged on as PNG files named after the overlay: `<overlay name>_diff.png`, the colour difference against the
golden board, and `<overlay name>_ai2.png`, the AI score map in steps of 0.001 σ up to 32.767 σ and of 1/8192 of the
value above (`<overlay name>_ai.png` for results stored before this version, in 0.001 σ steps up to 65.535 σ). A map
file another program holds open, or a damaged one, shows error AOI-CMP-003 on Compare, and such an overlay picture
AOI-CMP-006; the stored verdict and decision table still stand. A map an image editor saved again (in colour, or at
another size or bit depth) counts as damaged, so edit copies of these files, never the files themselves. The maps of
OK results are deleted at start-up once older than `map_retention_days_ok` days (7, set in `settings.json` in the
default workspace folder; 0 deletes them at the next start); NG and WARN maps, and every record, overlay and check, are
kept. Each sweep is in the audit trail as `maps.sweep`; a file the app cannot delete (open in another program) is tried
again at the next start.

(to be written: history, archive, the audit trail, error codes)
