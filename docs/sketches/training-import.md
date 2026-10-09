# Training: import samples

Sketch for stage S02; used by stage S31. Frame and patterns: [frame-and-patterns.md](frame-and-patterns.md).
The Training page has four tabs: Samples (this sketch and [training-labels.md](training-labels.md)), Datasets
([training-datasets.md](training-datasets.md)), Train and AI models ([training-run-and-versions.md](training-run-and-versions.md)).

## Page and roles

Training › Samples (Engineering). Engineer and Admin.

## Wireframe (1920 × 1080; the import sheet opens inline above the samples table)

```
Training   TBOX-A1 · 40 OK · 3 NG · 1 UNSURE            │ Samples │ Datasets │ Train │ AI models │
[Add OK Images…] [Add NG Images…] [Import Folder…]
┌ Import 200 files ───────────────────────────────────────────────────────────────────────────────┐
│ View (● Top) ( Side) ( Bottom)     Label for all: (● OK) ( NG) ( UNSURE)                         │
│ Defect type for NG files  [Component ▾] [Polarity Error · Critical ▾]   (one of the 33 DCT types) │
│ ┌──────────────────────────┬───────┬────────────────┬──────┬──────────────────────────────────┐ │
│ │ File                     │ Label │ Defect type    │ View │ Status                           │ │
│ │ ok/ok_041.png            │ OK    │ —              │ Top  │ ✓ copied                         │ │
│ │ ng/polarity_error/n3.png │ NG    │ Polarity Error │ Top  │ ✓ copied                         │ │
│ │ ng/n7.tif                │ NG    │ [pick type ▾]  │ Top  │ waiting: type needed             │ │
│ │ ng/big.tif               │ —     │ —              │ —    │ refused AOI-TRN-002: 62 MP > 50  │ │
│ └──────────────────────────┴───────┴────────────────┴──────┴──────────────────────────────────┘ │
│ Copying 128 of 200  [████████████░░░░░░░░] 64 % · about 1 min left              [Cancel] [■ Import] │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ Samples ─────────────────────────────────────────────────────────────────────────────────────────┐
│ ID │ Label │ Defect types      │ View │ Labelled by │ Checked by │ File            (see labels sketch) │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Files are copied into the workspace and never modified; the source stays where it was. Folder import reads `ok/`
and `ng/` sub-folders; `ng/<Defect Type>/` pre-fills the type (folder names matched to the 33 DCT names, spaces
or underscores). Every NG file needs one of the 33 types before Import enables; "Unknown" is not offered
(REQ-TRN-001). Import runs off the UI thread: 200 files of 20 MP without a freeze over 2 s; the sheet shows
progress, time left and Cancel once it passes 10 s.

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Add OK images | Add OK Images… | Ctrl+O | B | File picker, PNG, JPG, BMP, TIFF; opens the sheet with Label OK |
| Add NG images | Add NG Images… | Ctrl+N | B | Opens the sheet with Label NG and the type picker |
| Import folder | Import Folder… | Ctrl+Shift+O | B | Folder with ok/ and ng/; files elsewhere are listed as "unsorted: pick a label" |
| View | Top / Side / Bottom | — | T (segmented) | Applies to all rows; a row can override it |
| Label for all | OK / NG / UNSURE | — | T (segmented) | Applies to all rows; a row can override it |
| Defect type | category, then type with its severity | — | F | 33 DCT types grouped by the 6 categories; severity shown read-only |
| Row override | per row Label, Defect type, View | — | F in table | For mixed batches |
| Import | Import | Enter | B | The page's one blue primary while the sheet is open; disabled until every NG row has a type |
| Cancel | Cancel | Esc | B | Keeps the files already copied, lists the rest as "not imported" |
| Refused list | n files refused | — | text | Stays at the foot of the sheet after import, with code and reason per file; [Copy List] |

## Empty state

Samples table: "No samples for TBOX-A1 yet. Add at least 20 OK boards per view, then NG boards with their defect
types." with [Add OK Images…]. Import sheet with no accepted file: "Nothing to import: every file was refused
(see the list)."

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-TRN-001 | A file was refused | Not an image (PNG, JPG, BMP, TIFF) | Leave it out |
| AOI-TRN-002 | A file was refused | Over 50 MP or 200 MB (proposed, as REQ-INSP-001) | Resize it, or raise the limit in Settings |
| AOI-TRN-003 | A file was skipped | The same image (SHA-256) is already in the dataset | Nothing to do; listed, not an error |
| AOI-TRN-004 | A file was not imported | It is in neither ok/ nor ng/ | Pick a label in its row |
| AOI-TRN-005 | Copying stopped | Disk full or the workspace is not writable | Free space; press Import again to copy the rest |
| AOI-TRN-006 | Import cancelled | — | n files copied, m not; the list shows which |
| AOI-TRN-007 | The dataset is frozen | A frozen version cannot gain files | Files are added to the working set; the next freeze makes a new version (REQ-TRN-005) |

## Requirements served

REQ-TRN-001, REQ-INSP-001 (same limits), REQ-SET-021, REQ-SET-019, REQ-TRN-005 (frozen versions stay as they are).

## Rules applied

Role first; one blue primary (Import while the sheet is open, otherwise Freeze Dataset on the Datasets tab); no
dialog over a dialog (file picker, then an inline sheet); progress with time left and Cancel over 10 s; no dead
ends (refused files listed with codes); glossary (Defect, Severity, Board model, Workspace); sizes; every string
through `self.tr()`.

## Decisions (2026-10-02)

- Q29: An NG image with several defect types is imported with its main type; the others are added as boxes later. Reason: REQ-TRN-001 asks for one type at import; S33's box editor adds the rest.
- Q30: Training images take the inspection limits from Settings, 50 MP and 200 MB. Reason: Built as settings in #121 and #122; one limit and one refusal everywhere.
- Q31: Duplicates (same SHA-256) are skipped with a count; the batch goes on. Reason: AOI-TRN-003 lists them; refusing a 200-file batch for one duplicate helps nobody.
- Q32: The View picker stays, default Top. Reason: Every image keeps its view tag (REQ-INSP-010) and dataset names carry the view, so Stage 2's Side and Bottom need no relabelling.
