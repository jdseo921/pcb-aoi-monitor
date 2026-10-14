# Home: the first-run guide for one person

Sketch for B5 of the 2026-10 business-readiness brief (D4; REQ-TRN-021). Frame, size classes, empty-state, error and
progress patterns: [frame-and-patterns.md](frame-and-patterns.md). It replaces Home's "No board model yet" block of
[home-step-cards.md](home-step-cards.md) and drives, in fewer actions, the steps of
[training-import.md](training-import.md), [training-labels.md](training-labels.md),
[training-datasets.md](training-datasets.md), [training-run-and-versions.md](training-run-and-versions.md),
[model-test.md](model-test.md) and [inspection-run-controls.md](inspection-run-controls.md). It counts what is missing
as [what-is-missing.md](what-is-missing.md) does.

The brief is not in the repository (see the progress file), so this sketch follows Jay's message of 2026-10-13
19:59 UTC. Where the brief says otherwise, the brief wins and this sketch changes before any code is written.

## Page and roles

Home, in the place of the six step cards, for the board model in the header from its making until its first board is
inspected, or until **Show All Steps ›** is pressed, which puts the cards back for that board model. With no board model
in the workspace the guide starts at screen 1; a board model made with + New in the header opens it at screen 2 when it
is in a customer's store. One made with no customer shows the six cards as today, as its images cannot be frozen until
an Admin moves it in. The guide is a part of Home, not a wizard window: the header and the sidebar stay, and every
Engineering page is one click away, except while the recovery key shows. The guide's screens replace one another in
Home's content area, and it shows no dialog of its own: a refusal is said under the control that raised it.

- **Admin**: the whole guide. A workspace with no board model starts signed in as its first Admin
  (`AppContext.start_user`).
- **Engineer**: screens 2 and 3. Screen 1 shows its fields and Create greyed, with "Setting up a board model for a
  customer needs the Admin role.", because the customer's encrypted store is the Admin's (ADR 0021; REQ-USR-001).
- **Operator**: no controls. With no board model: "No board model yet. Ask an Admin to set up the first one." With one
  being set up: "TBOX-A1 is still being set up." Neither has a button, as the frame's empty-state pattern says for a
  role that cannot take the step.

## The flow at a glance

```
Screen 1  Board model   name, customer → Create → the recovery key, saved or printed → I Have Saved the Key
Screen 2  Images        Pick Folder… (ok/ and ng/<defect>/) → copied and counted → one box on each NG image
Screen 3  Train         Train → keep images apart → train → make active → validate → shift check → the result
Screen 4  Inspection    Inspect a Board… → pick the image → the verdict
          then, outside the count: Open Logs & Export ›, or Start the Checks › for an Engineer
```

## Wireframes (1366 × 768, production theme; the frame as in frame-and-patterns.md, its 200 px sidebar not drawn)

Screen 1, before Create. The name field has the focus; the line under it is the live check of ADR 0023 (#409, #410).

```
┌ Set up your first board model ──────────────────────────────────────────────────────────── [Show All Steps ›] ┐
│ ● 1 Board model ─────────── ○ 2 Images ─────────── ○ 3 Train                                                  │
│ Board model name  [TBOX-A1                      ]  as on the board or its drawing, such as TBOX-A1            │
│                   ✓ TBOX-A1 can be used.                                                                      │
│ Customer          [Hanil Electronics            ]  whose boards these are; your company's name for your own   │
│ Each customer's images are kept encrypted on this station, apart from every other customer's.                 │
│                                                                                        [■ Create]  Enter      │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Screen 1, after Create: the same screen. The fields fold to one line and the recovery key shows below it, once. Until I
Have Saved the Key is pressed, the sidebar, the header's controls, Switch User and the window's close do nothing, as
the modal key dialog of #407 keeps them (ADR 0021, decision 3; showing it here and not in that dialog is Q67).

```
┌ Set up your first board model ────────────────────────────────────────────────────────────────────────────────┐
│ ✓ 1 Board model ─────────── ○ 2 Images ─────────── ○ 3 Train                                                  │
│ ✓ TBOX-A1 · for Hanil Electronics                                                                             │
│ Recovery key for Hanil Electronics                                                                            │
│ If this station's own key is ever lost, this key opens Hanil Electronics' images again. It is shown only now. │
│     K7Q2 9F4M A1C8 … (13 groups of four) … T8XW                                                               │
│ [Save to File…] Ctrl+S    [Print…] Ctrl+P        ✓ Saved to F:\recovery-key-Hanil-Electronics.txt             │
│ Save it on a USB drive that stays away from this station, not the one that brings the images, or print it.    │
│                                                                          [■ I Have Saved the Key]  Enter      │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Screen 2, before any image. The sentence is `datasets.needs()` without its last clause, on Validated versions (a Trial
form from the same constants); the folder rule is training-import.md's; the lines are What is missing's.

```
┌ Set up TBOX-A1 ─────────────────────────────────────────────────────────────────────────── [Show All Steps ›] ┐
│ ✓ 1 Board model ─────────── ● 2 Images ─────────── ○ 3 Train                                                  │
│ No images of TBOX-A1 yet                                                                                      │
│ A board model needs at least 70 OK images of one view (20 to train, 50 held out to test) and 1 or more NG     │
│ images with every defect boxed.                                                                               │
│ Pick one folder with two folders in it: ok, with the good boards' images, and ng, with a folder for each      │
│ defect named after it, such as ng\Missing Component.                                                          │
│ View  (•) Top  ( ) Bottom  ( ) Side                                               [■ Pick Folder…]  Ctrl+O    │
│ ○ OK images: 0 of 70                                                                                          │
│ ○ NG images: 0 of 1                                                                                           │
│ ○ NG images with every defect boxed: 0 of 1                                                                   │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Screen 2, once the images are in. The copy shows the progress pattern's line while it runs; then the help folds to
one line and the box area, always ready to draw, takes its place: a drag draws the box, saves it with the type its
folder gives and opens the next NG image without a box (Q70).

```
┌ Set up TBOX-A1 ─────────────────────────────────────────────────────────────────────────── [Show All Steps ›] ┐
│ ✓ 1 Board model ─────────── ● 2 Images ─────────── ○ 3 Train                                                  │
│ ✓ OK images: 90 of 70    ✓ NG images: 10 of 1    ○ NG images with every defect boxed: 3 of 10                 │
│ From E:\TBOX-A1, Top view. Not taken: 0.                                          [■ Pick Folder…]  Ctrl+O    │
│ ┌─────────────────────────────────────────────────────────────────────────┐  Draw a box around the defect.    │
│ │                                                                         │  Image 4 of 10 · n04.png          │
│ │                                                                         │  Missing Component (its folder)   │
│ │           NG image: drag across the defect                              │  The next image opens after       │
│ │                                                                         │  each box.                        │
│ │                                                                         │  [← Back] PgUp  [Undo] Ctrl+Z     │
│ └─────────────────────────────────────────────────────────────────────────┘ [Zoom In] + [Zoom Out] -  [Fit] 0 │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Screen 3. It shows itself when the last line of screen 2 is met (Q69), with Train focused. The board revision is asked
here, where the images are frozen with it, so nothing has to keep it in between.

```
┌ Set up TBOX-A1 ─────────────────────────────────────────────────────────────────────────── [Show All Steps ›] ┐
│ ✓ 1 Board model ─────────── ✓ 2 Images ─────────── ● 3 Train                                                  │
│ 90 OK and 10 NG images of the Top view are ready, every defect boxed.                                         │
│ Train keeps 50 OK and 3 NG images apart, trains the AI model on the other 40 OK and 7 NG as a Trial, since    │
│ one person labelled them, makes it the AI model that judges TBOX-A1's boards, tests it on the images kept     │
│ apart and runs the first shift check. Other pages can be used while it runs.                                  │
│ Board revision  [R1        ]  as printed on the board; leave R1 if it shows none                              │
│                                                                              [■ Train]  Enter  (T+)           │
│ Training the AI model: round 12 of 60 · 46 % · about 4 min left                             [Cancel]  Esc     │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Screen 3, when Train has ended. Rates are `stats.text` as AI Model Test words them: counts first, then the bound.

```
┌ Set up TBOX-A1 ─────────────────────────────────────────────────────────────────────────── [Show All Steps ›] ┐
│ ✓ 1 Board model ─────────── ✓ 2 Images ─────────── ✓ 3 Train                                                  │
│ ✓ AI model v1.0 (Trial) judges TBOX-A1's boards.                                                              │
│ Trained on 40 OK and 7 NG images. On the 50 OK and 3 NG images kept apart:                                    │
│   Missed defects  0 of 3, 95 % upper bound 63.2 %       False calls  1 of 50, 95 % upper bound 9.1 %          │
│ Trial: one person labelled the images and no one else checked them.                                           │
│ ✓ Shift check: every verdict right · boards may be inspected until 07:40                                      │
│ [■ Inspect a Board…]  Enter          [Open Logs & Export ›]          [Start the Checks ›]                     │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The counts carry AI Model Test's marker "Synthetic boards: not accuracy" whenever its rule marks a run so
(model-test.md). The demo opens with an active AI model, so the guide never shows there.

## Controls

Every label is a `self.tr()` string with named `{placeholders}`, in the Charter's words; the words the glossary does
not hold yet are Q77. The guide's own words never include dataset, version, freeze, split, lock, manifest, store,
epoch or seed.

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Steps | 1 Board model · 2 Images · 3 Train | — | text, 16 pt | ● now, ✓ done, ○ not yet; read again from the board model each time Home opens |
| Back to the cards | Show All Steps › | — | B | Home's six cards and What is missing for this board model; on the cards, "Show the Guide ›" returns until its first board is inspected |
| Name | Board model name | — | F | Focused on screen 1; the live line of ADR 0023 under it, its code first when refused, and Create off |
| Customer | Customer | — | F | Required: a board model's images are frozen only from its customer's store (AOI-TRN-027); an existing customer's name, any case, joins their store and shows no new key (ADR 0021) |
| Create | Create | Enter | T, blue | `create_customer_board_model`; off until name and customer are typed and the name may be used |
| Save key | Save to File… | Ctrl+S | T | As in #407, but the save dialog opens on the USB drive plugged in last, if any, else the home folder (Q68); "✓ Saved to {path}" beside it |
| Print key | Print… | Ctrl+P | T | As in #407; "✓ Sent to {printer}" beside it |
| Key done | I Have Saved the Key | Enter | T, blue | Off until the key was saved or printed, and a press while off says so on the status bar; it replaces the tick and Done (Q67) |
| View | Top / Bottom / Side | — | T | Top at first; every image of one pick gets the view picked |
| Images | Pick Folder… | Ctrl+O | T, blue | The folder dialog opens on the USB drive plugged in last (Q68); the copy starts on the pick when every image has a label and a type from its folder (Q69) |
| Type for a plain ng folder | Defect type for the images in ng | — | F (list) | Only when ng holds images directly; one of the 37 types; the copy starts once it is picked (Q71) |
| Not taken | Show Why | — | B | Each image not taken, with its code's line in the guide's words (Errors below) |
| Box area | (the NG image) | drag | — | Always drawing; the box gets its folder's type and the type's severity; the next NG image without a box opens |
| Back | ← Back | PgUp | B | The image before, to add a second box or move one |
| Undo | Undo | Ctrl+Z | B | Removes the last box drawn |
| Zoom | Zoom In / Zoom Out / Fit | + / - / 0 | B | As the label editor's (training-labels.md) |
| Revision | Board revision | — | F | On screen 3, prefilled R1 (Q74); 1 to 16 letters and digits, said under it as typed; kept in the version Train freezes |
| Train | Train | Enter | T+, blue | Off while another training runs (AOI-TRN-047); greyed while it runs |
| Cancel | Cancel | Esc | B | Stops within 10 s, as training's Cancel does; what it keeps is in "What Train does" |
| Inspect | Inspect a Board… | Enter | T, blue | Opens Inspection and its Load Images… file dialog on the folder above screen 2's folder; the board is inspected on Open (Q69) |
| Export | Open Logs & Export › | — | B | Logs & Export with the history of this board model |
| Validated | Start the Checks › | — | B | Inspection's label for this step (ADR 0020); here it opens Training › What is missing with Validated picked (B3, #408) |

## What Train does

One press runs five parts in order, off the window's thread (REQ-SET-021), each the service call the Engineering pages
make today. A part already done for the same images is not done again, so a second press after a Cancel, a refusal or
a restart goes on from the first part not done.

1. **Keep images apart.** Freezes the board model's images of the view as a Trial version (ADR 0020; Q80), with the
   customer of screen 1, the revision of screen 3 and the use "own" only (Q73), then splits and locks its validation
   set with a random seed (`lock_validation_set`): 50 OK and 30 % of the NG images, as REQ-TRN-006 asks. A frozen and
   locked version of the same images is used again, never frozen twice.
2. **Train** from the locked version, as Start Training does (REQ-TRN-008): the Golden board and the AI model.
3. **Make it active.** A board model's first AI model goes live when trained (ADR 0018); a Trial one does not today
   (ADR 0020, decision 4; AOI-TRN-052). Jay's message names this part, so the guide needs Q63. Under "Never live"
   parts 3 and 4 are left out, as part 4 would measure the Golden board comparison alone: the result says the AI
   model waits, with Start the Checks ›, and Inspection judges with the Golden board only, AOI-TRN-052 in its alarm log.
4. **Validate** the active AI model on the images kept apart, stored as a run of AI Model Test is (REQ-TST-001), and
   shown as counts with their bounds (REQ-TST-002). The customer validation report still refuses a Trial (ADR 0020,
   decision 5; AOI-TST-009).
5. **Shift check** of the master samples (REQ-INSP-017, ADR 0014), so the first board is not refused with
   AOI-INSP-016 (Q72).

The one progress line, under Train, is the training panel's "{phase} · {percent} % · {left}", with the percent and
the time left ("estimating…", "less than a minute left", "about {minutes} min left") of the whole press.

| Part | Phase (the words shown) |
|---|---|
| 1 | Keeping {ok} OK and {ng} NG images apart for validation |
| 2 | Training's own, in order: Aligning {count} images to the reference board · Aligning image {n} of {count} · Building the Golden board: step {n} of {count} · Golden board, part {band} of {bands}: image {n} of {count} · Training the AI model: round {epoch} of {epochs} (Q79) · Setting the threshold: image {n} of {count} · Saving AI model {version} |
| 3 | Making AI model {version} active |
| 4 | Validating AI model {version}: image {n} of {count} |
| 5 | Shift check: master sample {n} of {count} |

**Cancel** in part 1 or 3 waits for the transaction under way and stops after it; in part 2 it stops within 10 s and
keeps no AI model, as today; in part 4 or 5 the AI model stays active, the result says which part did not run, and
Inspection asks for Shift Check (F7) before the first board when part 5 did not run.

## Handover

- **Inspection.** Inspect a Board… opens Inspection with its Load Images… dialog; the image picked is inspected on
  Open, with no Start to press (Q69). From there Inspection is the page of inspection-run-controls.md: an NG or WARN
  opens Compare in one click. Home shows the six cards from then on, card 2 reading "Active AI model v1.0 (Trial)".
- **Logs & Export.** Open Logs & Export › opens the history with the first board's record; Export CSV, Confirm export
  and Save are the Admin's, as logs-history.md says (REQ-LOG-002): 4 actions and a fifth screen, outside the count.
- **The Validated path.** Start the Checks › opens Training › What is missing with Validated picked: the second-user
  label checks, the 10 % of OK labels, the 100 images of a calibration set and the agreement check, each with its
  button (B3, #408). An Engineer also reaches every existing page from the sidebar or Show All Steps ›, at any step;
  what is done there shows in the guide, which reads the same counts. A Validated AI model goes live through the
  go-live gate (REQ-TRN-012) and takes the Trial one's place.

## Empty states

For the Admin with no board model, screen 1 is the empty state.

| Where | Heading and sentence | Next step |
|---|---|---|
| No board model, Engineer | Screen 1 greyed, with "Setting up a board model for a customer needs the Admin role." | Show All Steps › |
| No board model, Operator | "No board model yet. Ask an Admin to set up the first one." | none (no role to act) |
| Screen 2, no image | "No images of TBOX-A1 yet" and the Trial form of `datasets.needs()` | Pick Folder… |
| Screen 2, a folder with no ok or ng in it | "No images in ok or ng folders in {folder}. Put the good boards' images in ok and the defective ones in ng, in a folder named after the defect, then pick the folder again." | Pick Folder… |
| Screen 2, too few | "○ OK images: 62 of 70. Add 8 more to the ok folder and pick it again; images already in are skipped." | Pick Folder… |
| Screen 3, a master sample judged wrong | "Shift check of TBOX-A1: 1 of 2 master samples judged right." and "Boards are inspected only after every master sample is judged right." | Inspect a Board… (Inspection offers Shift Check, F7), or Show All Steps › |

## Errors

Each refusal is said in the step, under the control that raised it, as the catalogue's title, a line in the guide's
words, and the code; Show Details holds the catalogue's own text, which names Training's tabs (Q78). Codes and titles
are from `aoi/errors.py`.

| Screen | Code | Title | The guide's line |
|---|---|---|---|
| 1 | AOI-TRN-019 | Board model name not allowed | Leave out / : * ? " < > \ \| and control characters, end with no dot or space, and use no device name such as CON or NUL. |
| 1 | AOI-TRN-054 | … no Latin letter or digit | Add a letter A to Z or a digit, such as TBOX-A1 or 기판 2호. |
| 1 | AOI-TRN-005, AOI-TRN-055 | … already taken; … reads as another | {existing} is already here. Pick it in the top bar, or type another name. |
| 1 | AOI-TRN-056 | … version names would mix | This has the letters and digits of {existing}. Change or add a letter or digit. |
| 1 | AOI-TRN-044 | Dataset store not changed | Nothing was made: {reason}. |
| 1 | AOI-TRN-053 | No dataset store on this system | This computer cannot keep the key, so nothing was made. Set up on the station itself. |
| 1 | AOI-LOG-002 | Export not written | The key was not saved there ({reason}). Save it on a USB drive, or print it. |
| 1 | AOI-USR-001 | Not allowed for this role | Setting up a board model for a customer needs the Admin role. |
| 2 | AOI-INSP-001, -004, -006 | Image cannot be read; format; decoded | Not an image this app reads. Save it as PNG or JPG and pick the folder again. |
| 2 | AOI-INSP-005, -007 | Over the size limit; side too long | Not the camera's usual size. Use the image as the camera takes it. |
| 2 | AOI-TRN-013 | NG image needs a defect type | Put it in a folder of ng named after its defect, then pick the folder again. |
| 2 | AOI-TRN-014 | Image changed while it was copied | Wait until copying from the camera has ended, then pick the folder again. |
| 2 | AOI-TRN-015 | Image already imported | Taken once already; nothing to do. Not counted twice. |
| 2 | AOI-TRN-016 | Image has no label | Not in ok or ng. Move it into one and pick the folder again. |
| 2 | AOI-TRN-008, -009, -010 | Images not imported; stopped part-way; stopped by an error | Copying stopped at image {at} of {total}; the ones before it are kept. Check the USB drive and the free space, then pick the folder again. |
| 2 | AOI-TRN-011 | Images not imported: path too long | The workspace folder's path is too long. Pick a shorter one on Settings, then the folder again. |
| 2 | AOI-TRN-025 | Dataset store not opened | {customer}'s images cannot be opened on this station. An Admin types the saved recovery key on Settings (Restore Key…). |
| 2 | AOI-TRN-030, -031, -032 | Label not changed; box outside the image; sample not found | The box was not kept: {reason}. Draw it again. |
| 3 | AOI-TRN-027, -022 | Dataset not frozen; validation set not locked | {reason}. Nothing was kept; fix it on screen 2 and press Train again. |
| 3 | AOI-TRN-040 | … version name taken | Another board model's names would mix with this one's. Set the boards up under a new name. |
| 3 | AOI-TRN-041, -042 | … manifest not written; path too long | Nothing was kept. Free space on the workspace drive, or pick a shorter workspace folder on Settings. |
| 3 | AOI-TRN-047 | Training already running | Wait for the training under way to end, then press Train again. |
| 3 | AOI-TRN-045, -043, -004 | Training not started; locked images; cannot judge boards | {reason}. No AI model was made; add images of more good boards on screen 2 and press Train again. |
| 3 | AOI-TRN-052, -048, -049 | Does not go live; not made active; no card | The AI model was made but does not judge boards yet: {reason}. |
| 3 | AOI-TST-003 | The validation did not start | {reason}. The AI model judges boards; AI Model Test tests it again. |
| 4 | AOI-INSP-016 | Shift check needed | Press Shift Check (F7). |
| 4 | AOI-INSP-009, -010, -011, -008 | Golden board file; nothing can judge; image too small; result not saved | As Inspection says them today, in its alarm log. |

## Click count

An action is a click or tap, a drag, a key press that is not typing, or one field typed; reaching a field without the
focus is one more. A screen is an app page or a guide screen that replaces the one before; a system file or folder
dialog is not one (Q64). The count runs from the empty workspace to the first verdict. Assumed: a USB drive kept for
the key is plugged in for screen 1, and the images' USB drive for screen 2, holding `TBOX-A1\ok`,
`TBOX-A1\ng\<defect type>` and, beside that folder, the image of the board to inspect; each dialog opens on the drive
plugged in last (Q68), and plugging one in is not counted; each NG image shows one defect; no image is refused.

| # | Screen | Action | 90 OK + 10 NG | 70 OK + 10 NG |
|---|---|---|---|---|
| 1 | 1 Board model | Type the board model name (the field has the focus) | 1 | 1 |
| 2 | 1 | Tab to Customer | 1 | 1 |
| 3 | 1 | Type the customer | 1 | 1 |
| 4 | 1 | Create (Enter) | 1 | 1 |
| 5 | 1 | Save to File… | 1 | 1 |
| 6 | 1 | Save (the dialog is on the key's USB drive, the file named) | 1 | 1 |
| 7 | 1 | I Have Saved the Key | 1 | 1 |
| 8 | 2 Images | Pick Folder… (View stays Top) | 1 | 1 |
| 9 | 2 | Click TBOX-A1 in the folder dialog (it is on the images' USB drive) | 1 | 1 |
| 10 | 2 | Select Folder; the copy starts | 1 | 1 |
| 11–20 | 2 | One drag on each of the 10 NG images | 10 | 10 |
| 21 | 3 Train | Train (screen 3 showed itself; Board revision stays R1) | 1 | 1 |
| 22 | 4 Inspection | Inspect a Board… | 1 | 1 |
| 23 | 4 | Click the board's image in the file dialog | 1 | 1 |
| 24 | 4 | Open; the verdict shows | 1 | 1 |
| | | **Total, against 25 actions and 4 screens** | **24 actions, 4 screens** | **24 actions, 4 screens** |

Both cases take the same actions: Train keeps 50 OK and 3 NG apart in both, and trains on 40 OK and 7 NG, or on 20 OK
and 7 NG, which is the least training takes (`datasets.TRAIN_OK`). The two differ in what one refused image costs.

| What changes | Actions | Total |
|---|---|---|
| 90 + 10: up to 20 OK images refused or taken twice | 0 (90 − 20 still meets 70) | 24 |
| 70 + 10: one OK image refused or taken twice | +3 (copy one into ok, then Pick Folder…, folder, Select Folder) | 27, over |
| A dialog that does not open on the right USB drive (Q68 not taken) | +1 each, up to 3 | up to 27, over |
| No shift check in Train (Q72 not taken): AOI-INSP-016's message, OK, Shift Check (F7), Start | +3 | 27, over |
| A plain ng folder with no defect folders | +2 (the type list, the type) | 26, over |
| An NG image with two defects | +2 each (← Back, a drag) | 26, over |
| Annotation files (Pascal VOC or YOLO) beside the images | −10, the boxes are read | 14 |
| Exporting the first record (Q64) | +4 and a 5th screen | 28 actions, 5 screens |
| The first-run wizard's first Admin, once built (Q65) | about +5 and a screen | about 29 actions, 5 screens |

Today the same path takes about 67 actions on about 13 pages, tabs and sheets, counted from the pages' code and not
clicked: Draw Box, a drag and Next on each NG image (30), and five steps on three Training tabs.

## Requirements served

REQ-TRN-021, REQ-TRN-001, REQ-TRN-003, REQ-TRN-005, REQ-TRN-006, REQ-TRN-008, REQ-TRN-012 (the go-live gate: Q63),
REQ-TRN-017, REQ-TST-001, REQ-TST-002 (counts with bounds), REQ-INSP-016, REQ-INSP-017 (the shift check),
REQ-SET-018, REQ-SET-019, REQ-SET-021, REQ-USR-001, REQ-USR-005 (the first-run wizard: Q65) and REQ-LOG-002.

## Rules applied

Role first (the Operator gets no setup controls; screen 1 is the Admin's, as the store is); verdict first (the guide
ends on Inspection's verdict); one frame, the sidebar and header kept; at most 2 clicks from Home (the guide is Home);
no dialog over a dialog, and no dialog of the guide's own; one blue button at a time (Create, I Have Saved the Key,
Pick Folder…, Train, Inspect a Board…); every empty state and refusal
says what to do with its code (REQ-SET-019); progress over 10 s with the phase, n of N, percent, time left and Cancel;
sizes: fields F, buttons B or T, the screens' blue buttons T and Train T+, text 14 pt and step names 16 pt; counts
with bounds, never a bare percent, and the synthetic marker; every string through `self.tr()`. Nothing here changes a
verdict: the guide calls today's checks in a new order.

Departures, each approved by Jay on 2026-10-14 (Questions, below): a Trial AI model goes live (Q63; REQ-TRN-012, a MUST; ADR 0020
decision 4); the key shown on screen 1, not in #407's modal dialog, with one button for the tick and Done (Q67; ADR
0021 decision 3); Train picks Trial with no choice offered (Q80; ADR 0020 decision 2); the guide's own line beside each
refusal, which is text outside `aoi/errors.py` until Q78 puts it there. SHOULD skipped, with this reason: Home shows
the guide in place of the six cards (REQ-INSP-016) because one person needs one next step, and the cards are one
press away under Show All Steps ›.

## Questions for Jay, decided 2026-10-14

Jay answered on 2026-10-14 at 00:03 UTC: "Yes to every questions." Each recommended answer below is the decision.

From Q63. Q63, Q67 and Q80 depart from a decision or a MUST; Q73 and Q77 are a contract and a Charter decision; the
rest are design choices, each with the answer I recommend. The count of 24 holds with Q64 and Q67 to Q72 as
recommended: without Q67 it is 25, and without any one of Q68 to Q72 it is over 25.

1. **Q63. Does the guide's first AI model, a Trial one, judge boards?** Recommended: **"Live until Validated"**, the
   third option of the card of 2026-10-13 06:15 UTC. A Trial AI model goes live only while no Validated one has, and
   never replaces one; every screen, record and report names it Trial, and the customer validation report still
   refuses it. Your B1 message said the go-live gate refuses a Trial version; this one lists "activate the first
   model" in Train. Under "Never live" the guide ends with the Golden board comparison only and AOI-TRN-052 in the
   alarm log, not the AI model just trained, and with no validation counts. It departs from REQ-TRN-012 and ADR 0020
   decision 4, so it needs your word.
2. **Q64. Is the count as "Click count" defines it, from the empty workspace to the first verdict?** Recommended: **yes**.
3. **Q65. Is the first-run wizard of ADR 0002 (the first Admin's name, password and recovery code) in the 25?**
   Recommended: **no**, counted apart: it is not built, and its 5 or so actions and a screen fit no layout of the 25.
4. **Q66. Does the recovery key stay on screen 1, right after Create?** Recommended: **yes**. The customer's images
   are encrypted from the first copy (REQ-TRN-017), so the store and its key must exist before screen 2.
5. **Q67. The key on screen 1 with the frame locked, in place of #407's modal dialog, and one button, I Have Saved the
   Key, in place of the tick and Done?** Recommended: **yes**. The lock keeps what the dialog keeps (the key cannot
   be left unsaved), and the button is off until the key was saved or printed, as the tick is. It saves an action, and
   a dialog would be a fifth screen if Q64 counts it as one.
6. **Q68. The key's save dialog, the folder dialog and Inspection's file dialog open on the USB drive plugged in last?**
   Recommended: **yes**, with the sentence that the key goes on a drive kept away from the station, not the one that
   brings the images. It saves up to 3 actions; with no drive, the key's dialog opens on the home folder as today.
7. **Q69. No extra presses?** The copy starts when the folder is picked, screen 3 shows itself, and Inspect a Board…
   inspects on Open. Recommended: **yes**; each saves one action, and the count needs all three.
8. **Q70. Boxes: always drawing, the next image after each box, ← Back for a second box?** Recommended: **yes**.
   With Draw Box and Next on each image, as the label editor has them, the 10 boxes take 30 actions.
9. **Q71. Do the acceptance cases assume a folder for each defect type in ng?** Recommended: **yes**; a plain ng
   folder costs 2 more actions, over the limit.
10. **Q72. Train also validates and runs the first shift check?** Recommended: **yes**; both add time, not actions.
    Without the shift check the first board is refused with AOI-INSP-016, which costs 3 actions.
11. **Q73. The guide freezes with the use "own" only?** Recommended: **yes**. Shared and demos need the customer's
    written leave and stay on Training's freeze sheet.
12. **Q74. Board revision on screen 3, prefilled R1?** Recommended: **yes**; it is used only where Train freezes.
13. **Q75. A restart before the first AI model is active opens the guide as the user who started it?** Today it signs
    in the user who signed in last, else the Operator, who cannot go on. Recommended: **yes**, until ADR 0002's sign-in.
14. **Q76. The guide lives on Home, in place of the cards, from the board model's making to its first inspected
    board?** Recommended: **yes**, with Show All Steps › for the cards and + New in the header for the next one.
15. **Q77. Add Customer, Recovery key, Trial, Validated, Shift check, Board revision and View to the Charter
    glossary?** Recommended: **yes**, with Korean drafts (고객, 뷰 and 보드 리비전 exist) for the native speaker.
16. **Q78. A second "what to do" line in `aoi/errors.py` for the codes the guide raises, in the guide's words?**
    Recommended: **yes**. Every message stays an `AoiError` from the catalogue, and `docs/error-codes.md` lists both.
17. **Q79. "Training epoch" and "Calibrating: map" read "Training the AI model: round" and "Setting the threshold:
    image", on Training's panel too?** Recommended: **yes**, one set of words for one run.
18. **Q80. Train freezes as Trial with no choice, saying so above the button?** ADR 0020 has the Freeze sheet open on
    Validated each time, so Trial is chosen. Recommended: **yes**: one person cannot take the Validated checks, and
    Start the Checks › leads to them afterwards.
