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
(`C:\AOI_Workspace`, not `AOI_Workspace`): an empty or relative folder is refused with AOI-SET-008 on the page before
anything is saved, and at start-up, where `settings.json` with a log retention, input size or epoch count below 1 is
refused with the same code. The
app writes only the settings it changes into `settings.json`, so a line you edit there while the app runs, such as an
image limit, stays; it takes effect at the next start. Saving needs the Admin role (AOI-USR-001) and writes an audit
entry, `settings.change`, with the values before and after. The last user with the Admin role cannot lose it
(AOI-USR-002): give another user the Admin role first. A user's role is the one set under Users & roles, at every
start too: the app starts with the Admin added first while the workspace has no board model, and with
`operator` after that, so a role you change holds after a restart.

**Presenter theme (demos).** For a demo, an Admin ticks Presenter theme on the Settings page, in its own group. It
applies at once, with no restart, and stays on after one: a light background, text of 18 pt or more, the verdict at 48
pt in the same colours and shapes, and black text on the green, red and blue fills. Settings (the Admin page) and 3D
Profile leave the sidebar for every role (the SYSTEM heading with Settings), so a demo never shows them, and the app
opens Home in their place; every other page stays where it was. Only an Admin leaves the theme, with Exit presenter
theme in the header, which the header shows to an Admin alone: an Operator or Engineer at the station switches the user
to an Admin first (Switch User), then presses it. Each switch, on or off, is saved in `settings.json` as
`presenter_theme` and written to the audit log as `settings.change`, like a save on Settings.

**The workspace folder.** The station keeps everything in one folder, its workspace: `aoi.sqlite`, the database of
records, recipes, AI model versions, users, alarms and the audit trail; `images`, the samples by board model and label;
`models`, each board model's AI model versions with their Golden boards and AI model cards; `datasets`, the manifests of
frozen dataset versions; `results`, the overlay and maps of each record, by day; `exports`, the folder the exports
offer; and `logs`, the app log (section 8). Paths inside it are stored relative to it, so the whole folder, copied with
the app closed, opens again from another folder or PC (a customer's dataset store then needs its key: Restore Key…,
section 3). By default it is `AOI_Workspace` in the Windows account's home folder, or the folder the `AOI_WORKSPACE`
environment variable names; that folder also holds `settings.json`, whichever workspace it names. To use another
workspace, type its full path in **Workspace (images, AI models, database)** or pick it with **Browse…**, then press
**Save Settings**. Nothing is copied: the next start opens that folder as it is, and makes an empty workspace there when
it holds none, with no board model and the users `operator`, `engineer` and `admin`; so copy the old folder's contents
into it first, with the app closed.

**The AI device.** **auto**, the default, trains and judges on a CUDA graphics card when PyTorch finds one, and on the
CPU when it does not; **cuda** does the same, so on a PC without such a card it too goes on with the CPU, with no
message; **cpu** keeps to the CPU. The **Device** line on Training names the device in use, and the app log names it
at each start (`app.start`) and at each change (`device.change`). When a change applies is in "Settings and
settings.json" above.

**What each setting takes.** On the Settings page, **Default input size** is 128, 256, 384 or 512 (256 at first),
**Default epochs** 5 to 1000 (60) and **Log retention (days)** 1 to 3650 (30): the age at which a record is archived,
at each start and with the archive button on Logs & Export (section 8). **Largest image (megapixels)** (50) and
**Largest image file (MB)** (200), `max_image_megapixels` and `max_image_megabytes` in `settings.json`, are the most an
image may hold before it is refused, undecoded, on Inspection and in an import (AOI-INSP-005), each a whole number of 1
or more; **Keep OK results' maps (days)** (7), `map_retention_days_ok`, is 0 or more (section 8, Evidence files). An
Admin sets them on Settings (#153). AOI-SET-008 refuses any other value, on Settings and at start-up, naming the
setting, the value and what it takes.

**Exports are an Admin's.** Customer images and results leave the station only by an Admin (#151): Export CSV and
Export Image Overlays on Logs & Export, Export CSV, Export Report and Validation Report… on AI Model Test and Export
Manifest… on Training show for an Admin alone, and AOI-USR-001 refuses an Engineer. An Engineer still archives, and
exports an AI model.

**Demo workspace.** The demo has a workspace of its own, beside the station's, with its own `settings.json`; section 9
says how an Admin opens and leaves it.

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

**Creating a board model.** Press **+ New** in the header (Engineer or Admin; an Operator is refused with AOI-USR-001)
and type the name under "Board model name (e.g. TBOX-A1 Rev2)"; spaces at its ends are dropped, and an empty name
creates nothing. The new board model is chosen in the header at once, on every page. A name that exists, typed exactly,
creates nothing and chooses that board model (the status bar says when it is already chosen); one that differs from an
existing name only in case, or that cannot name a folder, is refused (Names, above). The app has no step to rename or
delete a board model, so check the name before OK. Creating it writes `board_model.create` to the audit trail and
stores the default recipe as revision 1, saved by the system (`recipe.default`), so its first boards already name the
recipe revision that judged them. It has no Golden board, AI model or scale yet; Home shows how far it has come on six
cards, each with a link to its page. The steps, in order:

1. For a customer's images, an Admin moves the new board model into that customer's dataset store (Settings › Dataset
   stores, Move Board Model In…, section 3) before the first import: each image is then encrypted as it is copied, and
   never written plain.
2. On Training, import OK and NG images and make an OK one the reference with Set Reference (section 3). From then on
   Inspection compares boards with that Golden board, with AOI-TRN-003 in its alarm log while no AI model judges them.
3. Label, check and freeze a dataset version and lock its validation set (section 3), then train an AI model version
   from it and activate it (section 4).
4. On the Recipe Editor, set the scale (Scale, above), draw the ROIs and set the thresholds (section 5), and save the
   recipe.
5. On AI Model Test, test the active AI model on the locked validation set (section 6).

## 3. Samples, labels and datasets

**Set Reference** makes the selected OK sample the reference image: inspections compare against it at once, and the
next training run aligns the boards to it before it learns a new golden board. An NG sample is refused (AOI-TRN-006),
and the sample that is the reference cannot be relabelled NG or UNSURE or removed until another OK sample is set
(AOI-TRN-007); with several rows selected, Mark NG, Mark UNSURE and Remove change all the others and leave the
reference as it is. Remove asks first, with No as the default: Enter keeps the samples. Only an Admin removes a sample
(REQ-LOG-003): for an Engineer, Remove is off and its tooltip names the Admin role. The sample's record goes, its image
file stays in the workspace, and the audit trail records it as `sample.delete`.

**Mark NG** asks for no defect type: an NG image's boxes, each of one of the 33 types, give its types (below), so an
image marked NG has none until a box is drawn, which a second user's check needs before a freeze. An import gives each
NG sample one of the 33 types (AOI-TRN-013). **Mark OK** clears the type. Neither changes a sample's view.

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
check it. An NG image whose defect type is not one of the 33, as an earlier version could store, takes no box until
you mark it NG again (AOI-TRN-030 says so): Mark NG labels it NG with no type, as for any image, and its boxes then
give its types; Undo after another mark puts it back with no type either. An UNSURE image is left out of training and
its calibration and counted as neither OK nor NG on Training and Home. A box must lie inside the image (AOI-TRN-031);
a label an image cannot take, such as a box on an OK image or a type not one of the 33, is refused (AOI-TRN-030). The
label editor draws boxes and Mark UNSURE marks an image UNSURE (below); no screen lists UNSURE images for the
customer's quality engineer yet.

**Drawing defect boxes on the label editor (the S33 screen).** Select an image in Training's sample table and it opens
in the label editor beside the table: its file name, label and view above it, its boxes on it and listed under it. On
an NG image, press **Draw Box**, which stays blue while it is on, and drag around a defect: the box takes the type in
the **Type** list, and **Severity** beside it shows what the defect table gives that type; you cannot pick a severity
of your own. Select a box with a click or a tap on it, or by its row in the list: it turns yellow with a handle at
each corner, and the Type list shows its type, so picking another in the open list, or showing one with the arrow keys
and pressing Enter, changes it; the wheel turns the list only once you have clicked it, and nothing changes until you
pick. Drag a box to move it, or a handle of the selected box to resize it, with the mouse or a finger. On a large
image a box can be a few pixels on screen: a press inside the selected box still moves it, and its handles sit just
outside its corners. A box stays inside the image and is at least 4 by 4 pixels of the image; a shorter drag draws
nothing. Each box is saved, in whole pixels, when you let go, and each type when you pick it, as a new label in the
image's history with the boxes before kept. Images open and changes are saved in the background: until a change is
saved the image takes no other, and the status bar says to wait; one that takes over a second says so over the image.
An OK or UNSURE image takes no boxes, so Draw Box is off there. An image that cannot be read shows its error code
under its name; its boxes are listed but cannot be changed. To delete the selected box, press **Delete Box** or the
Delete key: it goes at once, with no question, and stays in the image's history. **Undo**, beside it, or Ctrl+Z puts
back what the last change replaced, on whichever image it was, which the table then selects; press it again for the
change before. Once another user signs in, or another board model is picked, what was changed before can no longer be
undone. **Mark OK**, **Mark NG** and **Mark UNSURE** under the table, or the keys O, N and U, label each selected
image at once, without asking; an image already so labelled stays as it is, unless its label has no labeller (see
Labels keep their history), and the rows stay selected. If an error stops the marks part-way, such as a database
another program holds, the images marked before it keep their new label, which the table shows and Undo puts back;
an Undo stopped so shows the images it put back. Once drawn, an NG image's boxes carry its defect types, which the
table's Defect type column shows, each with its count; Mark NG asks for no type and puts the focus on the image for
you to draw its boxes. An image marked OK or UNSURE loses its boxes, which stay in its history, and Undo or Ctrl+Z
gives them back with its label. While you type in a field, such as Epochs, in a drop-down list, such as the Type list,
or anywhere in the import sheet, the letters, digits and signs go there instead: a letter typed in a row's Label or
Defect type cell of the sheet opens its list on the value it starts. **PgDn** and **PgUp** open the next and previous
image of the table, in the order it is sorted. By keys alone: **D** presses Draw Box and puts the focus on the image,
where Enter places a box 64 pixels a side on screen at the middle of the image shown; the arrow keys move the selected
box by 1 pixel, 10 with Shift, and with Ctrl move its bottom right corner; keys pressed one after another are saved
once, half a second after the last. **Esc** leaves Draw mode, unless you are working in the import sheet: there Esc
closes the sheet. Tab moves between the image, the Type list and the Boxes list, where the up and down arrows select a
box. With no wheel, **Zoom In** and **Zoom Out** under the image and **Fit** beside Draw Box, or the keys +, - and 0,
zoom it by a click, a tap or a key; **Z** zooms to the selected box.

**A second user checks each label.** The labels of a board model and view are ready to freeze into a dataset only
once a second Engineer or Admin has checked every NG label and OK labels drawn at random, 10 % of them rounded up; the
draw's seed, count and labels are stored and audited, and a draw adds to earlier ones as OK images are added. You cannot
check a label you made (AOI-TRN-033). An NG image needs a defect box before its label is checked, an UNSURE label is
not checked, and a label from before this version, with no labeller, is labelled again first (AOI-TRN-034). A relabel
needs a new check. Until sign-in arrives in version 1.0, the second user is the second name picked in the user list,
which the validation report states. On Training, the samples table names each image's labeller (Labelled) and the
user who checked its label (Checked), and the line over it counts the checks a freeze still needs. Press **Draw OK
Labels to Check** to draw the OK labels, then pick **Unchecked** under Show: it lists every NG label and drawn OK label
not checked yet. The second user signs in with Switch User, selects the images and presses **Check Label** or Enter; it
checks each selected label they can check and says how many it left and why. It is off, its tooltip saying why, for an
image you labelled yourself; Enter typed in a field or a drop-down list stays the field's.

**Two labellers agree before a customer validation.** On Training, open the **Datasets** tab. **New Set** draws a
calibration set of 100 images of the board model, each labelled OK or NG: 30 NG images, or all when fewer, among the OK
ones, in a random order. It is off, its tooltip giving the count, while fewer than 100 images are so labelled. Each of
two Engineers then signs in with Switch User and presses **Label Blind…**: the set's images show one by one, "Image 1 of
100", with no file name, label, box or history, in place of the tabs. Press **Label OK** or O, or pick the defect type
and press **Label NG** or N; the next image follows. **Stop** or Esc leaves, keeping every label made, and Label Blind…
goes on from the next image; a sign-in or another board model in the header stops it too. The line under the set says
who has labelled how many images. Once two users have labelled every image, pick them under Labellers and press **Run
Agreement Check**: it counts the images on which the two agree on OK or NG, at least 98 of 100, and the images both
labelled NG on which they agree on the defect type, at least 90 % (both targets proposed), and shows both with ✓ or ✗.
Every check is stored with its counts, and the newest one decides whether a dataset version can be frozen. A set that is
not 100 such images (AOI-TRN-035), a second blind label (AOI-TRN-036) and a labeller who has not labelled every image
(AOI-TRN-037) are refused. Until sign-in arrives in version 1.0, each labeller is a name picked in the user list (ADR
0002).

**A frozen dataset version keeps its record.** Freezing takes the OK and NG images of one board model and view, with the
board revision, the customer and the allowed uses (their own AI models by default), as DS-TBOXA1-R3-TOP-v4: the board
model without hyphens, the revision, the view and a number counting per board model and view. It writes
datasets/<name>/manifest.json with each file's path, SHA-256, label, boxes, labeller and checker, and keeps the
manifest's SHA-256. It waits for every NG label (AOI-TRN-020) and the drawn OK labels (AOI-TRN-021) to be checked, a
customer (AOI-TRN-024) and an agreement check that reached its targets (AOI-TRN-027): the newest one of the board model
whose set holds images of the view decides, so a newer check short of the targets stops freezing until a newer one
reaches them. A board model whose name has no Latin letter or digit (AOI-TRN-039), or whose letters and digits name
another board model's versions (AOI-TRN-040), cannot be frozen; import its images under another name. A manifest that
cannot be written is AOI-TRN-041, or AOI-TRN-042 when its path is too long, and nothing of the version is kept. A
freeze refused by its checks reads no image file first. A datasets/<name> folder whose manifest no version lists was
left by a freeze that stopped before storing its version; the next freeze of that name replaces it. The version's record
and manifest never change, and a later label change goes into the next version. The version names the workspace's image
files rather than copying them; the app changes one only to encrypt it in its customer's store, and removes one only
when that store is shredded, but a file changed or removed outside the app cannot be recovered from the workspace, so
back the workspace up. Verifying a version hashes its manifest and every file
again and lists each file that changed or is missing since the freeze; train from another version when one did.

**Each customer's images are in a store of their own.** A version is frozen only from a board model in the dataset
store of the customer it names (AOI-TRN-027). An Admin keeps the stores under Settings › Dataset stores, one per
customer; each step there opens a sheet in the table's place. New Store… makes a store and shows its recovery sheet
once, with Print Sheet…: keep it apart from the station, since it is the only way to open the store on a new PC or
Windows account, where Restore Key… takes its 13 groups of four back. Close waits for the tick that says it is printed.
Move Board Model In… encrypts a board model's images and manifests where they are; they keep their .png and .json names
but open only in this app, on a station that holds the key. Cancel on its busy indicator leaves the rest plain, and the
same step, its button then reading Finish Moving In, moves them. A file the app cannot open is AOI-TRN-025, which says
why. When an engagement ends, an Admin shreds the store with Shred Store…, which names the board models and the files it
deletes and waits for the customer's name typed: its key goes first, then its images, versions, AI models and Golden
boards; nothing of it opens afterwards, a backup included, once the sheet is destroyed. A file that would not go is
AOI-TRN-044, and Shred Store… again deletes what is left (ADR 0010).

**Training › Datasets freezes, splits and checks versions.** The Working set panel counts each view's OK, NG and UNSURE
images and the checks a freeze needs, with ✓ once the view can be frozen, and names the customer whose dataset store
holds the board model; tick the allowed uses under it. **Freeze Dataset…** (Ctrl+F) shows the Freeze sheet in place of
the labeller agreement: pick the view and type the board revision, and the sheet names the version and shows a line for
each thing a freeze needs, ✓ or ✗ with the fix. **Freeze**, or Enter in the revision, freezes it in the background with
progress and Cancel; Cancel or Esc stops it, writes nothing and keeps the sheet. The **Versions** table lists the board
model's versions, newest first: when each was frozen and by whom, its OK and NG images, its locked validation set
("50 / 6") or "not locked", the customer, the uses and what Verify Manifest found. **Split and Lock Validation Set…**
shows a sheet for the version picked: its images against the 50 OK and 30 % of the NG that its validation set takes, its
NG images by defect type, and a random seed you may change. **Lock**, or Enter in the seed, splits the version once, for
good, and the status line counts both sets; the button is then off for that version, since a new split needs a new
version, and a version with fewer than 50 OK images cannot be locked. **Verify Manifest** hashes the version picked and
each of its files again, with progress and Cancel: ✓ when every file matches, else ✗ and, under the table, AOI-TRN-023
naming the files changed or missing; train from another version, or freeze the working set again. **Export Manifest…**
asks first, naming the file count, then writes the version as a CSV file, one row per image: its path, SHA-256, label,
defect type, boxes, labeller, checker and part of the split. Open Version, the sketch's read-only view of a version's
labels and boxes, comes later.

## 4. Training and AI model versions

**A model that cannot judge.** When training gives an AI model that cannot judge boards, for example an image threshold
of 0 because the OK images are copies of one photo, it stops with AOI-TRN-004: nothing is saved and the active AI model
stays in use. Import photos of several different good boards, then train again.

**An import** runs in the background (#194): the sample table shows "Importing…" after a second, and progress, the time
left and Cancel after ten. While any import runs, Add OK Images…, Add NG Images…, Import Folder… (also the link in an
empty sample table) and Start Training are off, "Importing…" stays over the table when the page is shown again, and a
Switch User does not stop it: the samples are recorded as added by the user who started the import. The line over the
sample table counts the OK and NG samples and names the reference image (under it, while fewer than 20 OK samples are
imported, a tip says that training needs 20 OK images or more in a dataset version's training set); a name too long for
the line is cut at its end (…), and pointing at the line shows it whole. If the system refuses the path of a sample's
copy in the workspace as too long (a workspace folder with a long path, on Windows with long paths off), the import
keeps the images it imported before that file and names AOI-TRN-011 in AOI-TRN-010; when that file was the first, it
shows AOI-TRN-011 itself, which counts every image it was to import. The steps are those of AOI-INSP-014 (section 8,
Evidence files).

**What a run trains on.** Start Training trains from a frozen dataset version, never from the sample table: pick it
in Dataset version, which lists the board model's frozen versions, newest first, and starts on the newest whose
validation set is locked; the line under it counts that version's validation set and training set. The run reads only
the training set: its OK images make the Golden board, three quarters of them train the AI model and the rest set the
threshold, which its NG images only help to set; the locked validation set is never read. The run does not start, and
saves nothing, when the version's validation set is not locked or its training set holds fewer than 20 OK images
(AOI-TRN-045), when an image of its training set is locked in any validation set (AOI-TRN-043), or when its images are
not in the dataset store of the customer it names or it does not allow the use (AOI-TRN-046, written to the audit log).
Locking keeps at least 50 OK images for validation, so a board model and view needs 70 or more. An image changed since
the freeze stops the run with AOI-TRN-045 naming the file. The new AI model names the version it was trained from.
Freeze a version and lock its validation set on the Datasets tab (section 3).

**While a run goes on**, the line under the bar names what it does now, with its percent and the time left: "Aligning
image 12 of 53", "Building the Golden board: step 3 of 16", "Training epoch 23 of 60", "Calibrating: map 4 of 16", then
"Saving AI model v1.3". The time left reads "estimating…" for the run's first image only, then "about 6 min left", or
"less than a minute left"; the line and the bar change at least every 10 s. The run goes on whichever page you open: the
header shows "Training 38 % · about 6 min left" on every page, and Home's Train AI model card "Training running 38 % · about
6 min left"; press the header's button to come back to Training. Start Training stays off while a run goes on, one run
at a time (AOI-TRN-047).

**Cancel** ends a training run without saving anything: no AI model version, golden board or audit entry; the active AI
model stays. The run stops after the image, step or map in hand, within seconds, or as it saves, before the new AI model
is registered, and the log says "Cancelled: no AI model was saved; the active AI model is unchanged." Closing the app
while work runs asks whether to stop it; an AI model test finishes its folder first.

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
raises no AOI-INSP-013, though the boards after it name the version now active, and neither does a training run, which
installs its version inactive with its Golden board (section 4, Versions).
A scale set changes nothing that judges a board while the recipe holds its sizes in px, so it then moves no run, with
the AI check on or off.

**Threshold column.** Each AI model version's calibrated AI score threshold, which judges the board model's boards while
the recipe holds no override of its own (section 5). A version whose calibrated value the AI model registry cannot give,
which only a change made by hand leaves, reads AOI-TRN-012, with what happened and what to do as the row's tooltip
and in a line under the table: for the next boards, train again or activate another version, or set a value of your
own for the board model (section 5). Where such a row's sample counts cannot be read either, its OK/NG cell stays
empty.

**Versions, activation and rollback.** Each training run adds a version to the AI models list with its Golden board
and its AI model card, inactive: boards stay judged by the active version until you select the new one and press
Activate Selected. Activating a version makes its own Golden board the one boards are compared with, in the same step.
Roll Back goes back, in one click, to the version that was active before the active one, with its Golden board; its
label names that version ("Roll Back to v1.0") and it is off while there is none. Every activation and rollback is in
the audit trail with the version and Golden board before and after. A version without an AI model card cannot be made
active (AOI-TRN-049), nor one whose Golden board cannot be read (AOI-TRN-048); the version in use stays.

**AI model card.** Select a version and press AI Model Card to read its card under the list: what it is and what it
was trained on (dataset version, customer, seed, code, settings, who trained it and when), the set-up, its thresholds,
its known limits and the sign-off lines for the AI lead and the quality lead. Its first line says it is not yet tested
on a locked validation set, and it gives no rate: the card is written when the version is trained, and a later AI Model
Test does not fill it in yet. The counts of a test are on AI Model Test's tiles and in its Validation Report…. Export
AI Model… writes the weights-only `.pt` with its card beside it, as `.card.md` and `.card.json`.

## 5. Recipes

**A board is never passed on no evidence.** A board model with neither a Golden board nor an AI model, or a recipe
that turns off both "Use the Golden board comparison" and "Use the self-trained AI model", judges nothing: every
board is refused with AOI-INSP-010, which names why each check did not run. A Golden board whose file is gone or
damaged refuses every board of its board model with AOI-INSP-009: put the file back, or choose another OK sample as
the Golden board with Set Reference on Training. Training again does not cure a damaged file, since a run reads the
Golden board first to align every image to it. The Recipe Editor and Compare show such a Golden board as one
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
below 0, leaves a threshold unset. Apply refuses other values with AOI-RCP-002 and changes nothing. The 3D Profile page
(its sidebar entry marked "Stage 2") says the same until the Stage 2 3D camera: it is one card, "Coming in Stage 2",
and its Open Recipe Editor › (Enter) brings you here; Back to Home (Esc) leaves it.

**Save Recipe** (Ctrl+S) never overwrites a revision. It opens a sheet under the tabs that names the revision it will
make and lists what changes from the latest one, before → after ("Pixel difference: 45 → 30", "ROI R3 added"), and the
mandatory AOI checks the recipe leaves uncovered (see AOI checks below). Nothing is saved until you press Save Revision
(named with the revision's number); Cancel or Esc closes the sheet. Save Revision is off while nothing has changed, and
while a Stage 1 check is uncovered until you type a reason, which is kept with the revision in its audit entry. If you
change the recipe while the sheet is open, Save Revision shows the sheet again with the new changes before anything is
saved. When a revision was saved after the Recipe Editor loaded its own, for example with Save to Recipe on Compare, the
editor shows it when opened again; if the editor holds changes not yet saved, it asks first. Choosing No keeps them on
screen, but Save Recipe then refuses (AOI-RCP-001) until the newer revision is loaded, so a save never undoes another
without notice. Picking another board model cancels a Try Recipe… still running and clears the last Try's verdict.

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

**ROIs** (on the Golden board). Press Draw ROI (D) and drag on the board to draw an ROI of the Type picked; Esc
leaves Draw ROI. Click an ROI to select it: it turns yellow with a handle at each corner and in the middle of each side,
and its row and the Selected ROI form follow. Drag inside it to move it, or drag a handle to resize it: a corner moves
its two sides and a side's handle that side alone, while the opposite sides stay. With the focus on the board, an arrow
key moves it 1 px, Shift and an arrow 10 px, and Ctrl and an arrow moves its bottom right corner. An ROI never leaves
the board and is never under 4 px a side; one too small for its handles has them outside it, so a press inside it still
moves it. An ROI changed and not yet saved is yellow and dashed, a saved one green and a disabled one grey. Delete
removes the selected ROI without asking, since Ctrl+Z undoes each change to the ROIs since the revision was loaded
(drawing, moving, resizing, Apply, Delete) and Ctrl+Y does it again. The wheel zooms at the pointer; a drag on the
board away from an ROI pans, as does a middle-button drag or a drag with Space held (in Draw ROI too); Home or a
double-click fits the board. Save Recipe stores each ROI where it is shown, its box in mm under a scale (section 2).

**Try Recipe…** (Ctrl+T) judges a board with the recipe as it stands on screen, changes not saved included, and
stores nothing: no result and no file. The file dialog opens on the board last inspected under this board model, so
Enter tries that one, or pick another image. The Try runs off the screen with a busy indicator over the board; then
the board shows its defects in red with the ROIs, the line under the tabs gives the verdict, the number of defects and
the time taken, and the table under it lists each check behind the verdict as Compare's decision table does (value,
threshold, rule and result), with the inspection time against the 1 s budget.

**AOI checks** tab. The 10 mandatory AOI checks of the defect classification table, each marked by how the recipe
on screen covers it: ✓ ROI R1 for Missing Component, Polarity Error and Solder Bridge when an enabled ROI of the
matching type (Presence, Polarity, Solder Bridge) covers it; • whole board for Misalignment, Tombstone and Cold Joint
while the AI check or the Golden board comparison is on; ○ not covered; and ◌ needs Stage 2 for the 4 checks a 3D or
side camera makes. The marks follow each edit before it is saved.

**Revisions** tab. Every revision of the board model's recipe, newest first, with who saved it, when, what it changed
from the revision before (hover for the full list) and the reason given. Pick one and press Open to see it read-only
beside the recipe on screen: its settings, its ROIs and what your recipe changes from it; nothing in it can be edited.
Restore as New Revision opens the Save Recipe sheet for a copy of the revision picked as the next revision, listing what
it changes from the latest one; Save Revision saves it and shows it, after asking whether to discard any unsaved
changes. The revisions before stay as they were.

**The other thresholds** (Thresholds tab), each with its value in a new board model's recipe and the range its field
takes:

- **WARN band (fraction of the threshold)**, 0.80 (0.1 to 1): the AI score, the changed area and each ROI's AI score
  are WARN from this fraction of their threshold up to it. The similarity, NG below its threshold, is WARN over the
  same share of the distance from its threshold to 1 (from 0.80 to under 0.84 at the defaults). At 1 none of these
  checks gives WARN.
- **Pixel difference (0-255)**, 45 (1 to 255): how far a pixel's colour may differ from the Golden board's before it
  counts as changed.
- **Minimum defect area (px)**, 40 (1 to 100,000), or **Minimum defect size (mm)** under a scale (section 2): a region
  of change, or of the AI map, smaller than this is dropped as noise.
- **Similarity minimum (SSIM)**, 0.80 (0 to 1): the board's structural similarity to the Golden board, 1 for the same
  picture; below it the board is NG.
- **Maximum changed area %**, 0.50 (0 to 100): the share of the board's pixels changed by the pixel difference or more;
  at or above it the board is NG.
- **Allowed difference regions**, 0 (0 to 1000): the board is NG when the comparison finds more regions of change, each
  at least the minimum defect area, than this; it has no WARN band.

The pixel difference, the similarity, the changed area and the difference regions judge only while **Use the Golden
board comparison** is ticked and the board model has a Golden board. While it runs, Compare's decision table also shows
**Alignment points**, which no recipe sets: with fewer than 12 points matched between the board and the Golden board,
the board is WARN, as the other checks may be off. A board is NG when any check is NG, else WARN when any check is WARN
or a defect above Minor severity is on it, else OK.

## 6. AI model test and reports

**Source.** Pick what to test in **Source**: a frozen dataset version's locked validation set, listed first and picked
when the board model has one ("DS-…: its locked validation set, 51 images"), or a labelled folder with `ok/` and `ng/`
sub-folders (Select Test Folder… picks it). A dataset version's images keep the labels they were frozen with and are
checked against their SHA-256 as they are read; only a locked validation set counts as a validation (AOI-TST-003 when a
version has none). Run Test Again with the same AI model, recipe and data gives the same verdicts and scores.

**Rates with counts.** The five tiles lead with **Missed defects** (NG boards called OK, of the NG boards) and **False
calls** (OK boards called NG, of the OK boards), then Recall, Precision and Accuracy. Each reads its count, such as "0 of
50", with its exact one-sided 95 % bound under it ("95 % upper bound 5.8 %"): a rate is never a percent alone. A
validation on a dataset version also stores recall per defect type, by the type each image was frozen with.

**Results as they come.** The table grows as each board is judged, so the first row shows within a moment of Run Test. Selecting a row shows the overlay kept as the run judged it, with its verdict: it is never judged again, so a retrain, an activation or a new recipe since changes nothing it shows; the line above the table then names what judged the run and what is in use now, and Run Test Again tests the run's source with what is in use. A preview from a kept overlay leaves Compare's Use Last Inspected as it was. A run stored before this release keeps no overlay; its rows are judged again, as below.

**History.** The History tab lists every run of the board model, newest first: its time, AI model, dataset version or folder, recipe revision, missed defects and false calls. Select one and press Open (or double-click it) to show it on Run as it was stored, rows, tiles and previews.

**Export Report.** Asks first, naming how many images, missed defects and false calls the report holds; the PDF then gives the rates with their counts and bounds, recall per defect type, each missed defect and false call with its overlay, every row, and the card of the AI model that judged the run. It is written whole or not at all and recorded in the audit trail.

**Validation Report.** On History, select a run made on a frozen dataset version's locked validation set and press Validation Report…: the PDF follows the validation steps a customer signs: the data and the labeller agreement check, the targets agreed before testing beside the results, the locked set's manifest SHA-256, the results with counts and bounds, a page for each missed defect and false call, the AI model card, known limits and signature lines for the customer and the AI lead. A run on a folder, or a board model with no agreement check, has none (AOI-TST-007). The Korean headings are drafts for native review.

**Overlays.** AI Model Test has no overlay export. Each run keeps the overlay of each of its rows in the workspace,
under `results/test_runs/<run UUID>`, for its previews, and Export Report and Validation Report… print the overlay of
each missed defect and false call. The overlays of inspected boards are exported on Logs & Export with **Export Image
Overlays** (section 8): it asks first, naming the count, then copies the overlay picture of each record **Filter**
listed, under its own name (section 8, Evidence files), into the folder you pick, the workspace's `exports` folder
offered first; a record whose overlay file is gone is left out. The audit trail records it as `export.overlays`, with
the folder, the filter and the counts.

Each validation run is stored with a UUID and the UUID of the AI model active when it ran. **Export CSV** writes one row
per image (`image`, `gt` the label, `ai_result` the verdict, `score`, `defects`, `pass_fail`, `ai_check`, `defect_type` as
frozen, empty for a folder), then
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
Each export is confirmed first, naming the number of records, and written whole or not at all, the two CSV files
together. The audit trail records it with the filter that listed the records (From, To, board model, operator, result
and Include archived, as **Filter** applied them, not a box changed since) and their count, and the destination: a file
or folder inside the workspace, such as the suggested `exports` folder, relative to the workspace
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

The **From** and **To** boxes take days from 2000-01-01 to 2100-12-31. **Board model**, **Operator** and **Result**
(All, OK, NG or WARN) each narrow the list, and every filter combines with the others and with **Include archived**;
a click on a column's header sorts the table by it, again to reverse. The columns are Time, Board model, AI model
(its version), Result (the verdict's colour on that cell alone), Defects, Operator, View, Recipe rev and Image; the
record's ID and score are in the CSV export. **Open in Compare ›**, Enter or a double-click opens the selected record
on Compare as it was decided. With 100,000 records stored, **Filter** shows
its rows within 1 s (REQ-LOG-001); listing all of them at once takes much longer, so narrow the dates first. The
picture beside the table is the selected record's overlay; it is empty when the record's overlay file is gone, when no
row is selected and after **Filter**. When no record matches, the table offers **Reset Filters** (the last 7 days,
every board model, operator and result, archived records hidden); when every record is older than that or archived,
it offers **Show All Records** instead, which sets **From** to the oldest record's date, **To** to today and ticks
**Include archived** when any record is archived.

**Delete Records…** is the Admin's alone: an Engineer and an Operator do not see it, and the service refuses them with
AOI-USR-001. It deletes the records **Filter** listed, with their defects and checks and their overlay and map files in
the results folder; there is no undo, so archive records to keep them out of the list. It asks first, naming the count,
with No as the default, then asks why; a blank reason deletes nothing (AOI-LOG-003). The audit trail records it as
`inspection.delete`, with the user, the time, the filter, the records' UUIDs, the number of records and files, and the
reason. It runs in the background, "Deleting…" over the table. A file another app holds open stays: the records are
gone, AOI-LOG-004 names the first such file and the log names each one (`records.evidence_left`); close that app and
delete those files by hand (REQ-LOG-003).

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
kept until an Admin deletes the record (Delete Records…, above). Each sweep is in the audit trail as `maps.sweep`; a
file the app cannot delete (open in another program) is tried again at the next start.

**History.** Logs & Export reads the records in the background when it opens, with "Loading records…" over the table
after a second, and the exports and Delete Records… wait until they are listed. Its **Operator** box lists every user
of the workspace, whatever their role, and the line under the table adds how many records of the workspace are
archived. The Operator manual (section 5) and the paragraphs above give the rest.

**Archive.** At each start the app archives the records older than **Log retention (days)** (section 1), and **Archive
older than 30 days** on Logs & Export, which names the retention in force, does the same at once; it is grey for an
Operator. Archiving deletes and moves nothing: an archived record is only left out of the list until **Include
archived** is ticked, and opens on Compare and goes into an export like any other. No step brings a record back, so a
lower retention leaves the older records archived for good. The button's archive is in the audit trail as
`inspection.archive`, with the days and the count; the one at start-up is in the app log as `retention.archived`.

**The audit trail.** The audit trail keeps each change made in the app, from a recipe saved or an AI model version
activated to a label set, a setting saved or a record deleted, and each export. An entry holds the time (UTC), the
user's UUID and role, the action (such as `recipe.save` or `model.activate`), the object and its UUID, the object before
and after, and the reason when one was asked for; the sections above name the entries of each step. No entry can be
changed or deleted, by the app or by a database tool. A sign-in with Switch User is not an entry: each inspection record
names its user. No page of this version lists the trail; it is the `audit` table of `aoi.sqlite`, so read it from a copy
of that file, since a database tool that holds the station's file stops a change with AOI-SET-013 (section 1).

**Codes.** Every message shown when the app cannot do what was asked carries a code, `AOI-<area>-<number>`, whose area
names the part of the app: INSP Inspection, CMP Compare, TRN Training and datasets, TST AI Model Test, RCP recipes and
scale, LOG Logs & Export, USR users and roles, SET settings and the workspace. [The list of codes](../error-codes.md)
gives each one's title, what happened and what to do; it is made from the app's own catalogue, so it matches the build.
Each message shown is written to the app log, `logs/aoi-<date>.jsonl` in the workspace (one file per UTC day), as
`error.shown` with its code, the page, the details and the stack trace, naming a user only by UUID; and to the alarm log
on Inspection as `[ERROR]` (Operator manual, section 4). For AOI-SET-007, a fault the app did not expect, send that
day's log file to support (section 1 says where the log of a start that stopped goes).

## 9. Demo workspace

The demo shows a customer how the app works on drawn boards, never how well it finds defects: its results are not a
measure of accuracy and are never quoted as one. An Admin opens it on Settings › Demo with **Load Demo Workspace**. The
app closes the station's workspace and opens the demo's, a folder of its own beside the workspace named after it with
`-Demo` added (for `C:\AOI_Workspace`, `C:\AOI_Workspace-Demo`); the header shows a **Demo** badge and the board model
DEMO-TBOX-A1, with its AI model and card, its recipe, and 10 boards queued on Inspection, the fourth of them NG (a
missing component). Nothing in the station's workspace is read or written while the demo is open, its `settings.json`
included: the demo has its own.

- **Play Scripted Run ›** opens Inspection and presses Start: the boards are inspected and saved one after another at
  the **Scripted run pace** set on the slider, 1 to 10 s per board (3 s at first). The run pauses at the NG board, so
  **Compare with Golden board ›** can show why; Start goes on with the run, and Start after the last board plays it
  again from the first.
- **Reset Demo** (red) asks first, then deletes every result, record, alarm and log of the demo and every change made in
  it, and copies the demo back as installed, in under 10 s. The audit trail of the demo keeps the reset as
  `demo.reset`. If another program holds a file of the demo (AOI-SET-017), close it and press Reset Demo again.
- **Leave Demo Workspace** opens the station's workspace again. The demo stays as it is for the next time.
- To start straight in the demo, for example from a desktop shortcut kept for demos, start the app with `--demo`
  (`AOI-PoC-Inspector.exe --demo`); if the app closes during a demo, the same shortcut brings it back in the demo.

A folder of the demo's name that holds other files is never written to (AOI-SET-016): move or rename it. If the
installed demo is missing or was changed on disk, it is refused with AOI-SET-015: reinstall the app. Before a demo,
press Reset Demo so it starts clean (Customers & Launch, "Demos").
