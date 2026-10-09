# AI Model Test: rates with counts, live results and reports

Sketch for stage S02; used by stages S44 to S48. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

AI Model Test (Engineering). Engineer and Admin.

## Wireframe (1920 × 1080; at 1366 × 768 the tiles form two rows and the preview collapses to a button)

```
AI Model Test   TBOX-A1 · AI model [v1.2 active ▾]            │ Run │ History │
Source (● Dataset version [DS-TBOXA1-R3-TOP-v4 ▾], its locked validation set) ( Labelled folder [Select…])
[■ Run Test]  blue primary     Testing 37 of 51  [██████████████░░░░░░] 73 % · about 20 s left   [Cancel]
[ Synthetic boards: not accuracy ]  shown for a run on synthetic boards, and on every PDF page (S47)
┌ Missed defects ──────┐ ┌ False calls ───────┐ ┌ Recall ────────────┐ ┌ Precision ─────────┐ ┌ Accuracy ──────────┐
│ 0 of 1               │ │ 1 of 50            │ │ 1 of 1             │ │ 1 of 2             │ │ 50 of 51           │
│ 95 % upper bound 95 %│ │ 2.0 %, upper 9.1 % │ │ 100 %, lower 5 %   │ │ 50 %               │ │ 98.0 %             │
└──────────────────────┘ └────────────────────┘ └────────────────────┘ └────────────────────┘ └────────────────────┘
51 labelled of 51 images · TP 1  FN 0  FP 1  TN 49 · WARN counts as NG
┌ Recall per defect type ─────────────────┐ ┌ Results (grows board by board) ───────────────────┐ ┌ Preview ───────────┐
│ Type             │ Found    │ Severity  │ │ Image      │ Label │ Verdict │ AI score│ Pass/Fail│ │ [ ✗ NG ] banner    │
│ Polarity Error   │ 1 of 1   │ Critical  │ │ ok_019.png │ OK    │ ✓ OK    │ 0.46    │ Pass     │ │ overlay of the     │
│ Solder Bridge    │ 0 of 0   │ Critical  │ │ ok_014.png │ OK    │ ✗ NG    │ 1.12    │ Fail ■   │ │ selected row       │
└─────────────────────────────────────────┘ │ ng_003.png │ NG    │ ✗ NG    │ 3.81    │ Pass     │ │ [Open in Compare ›]│
                                            └───────────────────────────────────────────────────┘ └────────────────────┘
[Export CSV…] [Export Overlays…] [Export Report (PDF)…] [Validation Report…]   Stored 2026-10-01 13:52 · v1.2
```

Every rate reads "n of N" with a one-sided 95 % Clopper-Pearson bound, so 0 of 50 reads "95 % upper bound
5.8 %" (REQ-TST-002). The results table grows as each board finishes, first row within 2 s; failures are red and
read Fail (REQ-TST-003, -006). The preview comes from the stored overlay within 300 ms, not a new inspection.
Run Test Again with the same AI model and data gives identical verdicts (REQ-TST-001). WARN counts as NG in
Pass/Fail and in every rate, and the summary line says so, as `aoi/ui/pages/model_test.py` does at 329f603. A
one-line verdict banner above the preview shows the selected board's verdict with colour, shape and word (S18,
built in #98). A run on synthetic boards (the demo workspace, the synthetic regression set) shows "Synthetic
boards: not accuracy" above the tiles and on every PDF page (S47); its rates are never quoted as accuracy.

History tab: Time | AI model | Dataset or folder | Settings | Missed defects | False calls | [Open] reopens the
run with its tiles, table and exports (REQ-TST-005).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| AI model | AI model | — | F | Active by default; any version with a card can be tested |
| Source | Dataset version / Labelled folder | — | T (radio) + F | Dataset: the version's locked validation set only; folder: ok/ and ng/ sub-folders |
| Select folder | Select… | Ctrl+O | B | |
| Run Test | Run Test / Run Test Again | F5 | B | The page's one blue primary; runs off the UI thread |
| Cancel | Cancel | Esc | B | Partial run kept and marked "cancelled at 37 of 51", not stored as a validation |
| Tiles | Missed defects, False calls, Recall, Precision, Accuracy | — | text 26 pt value, 14 pt bound | Counts first, percent second; never a percent alone |
| Recall per type | Type, Found, Severity | — | rows 14 pt | One row per DCT type in the set, "n of N" (REQ-TST-007) |
| Results table | Image, Label, Verdict, AI score, Pass/Fail | ↑ ↓ | rows 14 pt | Columns in that order (names as built in #102); Verdict cells carry the shape; sortable after the run |
| Preview | Open in Compare › | Enter | B | Opens Compare on that stored result, failing checks highlighted |
| Export CSV | Export CSV… | — | B | UTF-8 with BOM, one row per image; confirmation names the count (REQ-TST-004) |
| Export overlays | Export Overlays… | — | B | Every miss and false call, then the rest; confirmation names the count |
| Export report | Export Report (PDF)… | — | B | Metrics with counts and bounds, overlays of every miss and false call, the model card; the same PDF serves the demo |
| Validation report | Validation Report… | — | B | The C&L validation steps: data, targets, locked set, results with counts and bounds, every miss and false call, signature lines for the customer and the AI lead (REQ-TST-008); needs a dataset-version run |

The four exports write customer images and results, so only an Admin sees them (Q58 in logs-history.md).

## Empty state

"No validation run for TBOX-A1 yet. Pick a dataset version or a labelled folder, then Run Test." with the source
focused. No AI model: "No AI model for TBOX-A1 yet. Train one on Training." with [Open Training ›]. History
without runs: "No runs stored yet."

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-TST-001 | The folder cannot be tested | No ok/ or ng/ sub-folder with images | Sort the images into ok/ and ng/ |
| AOI-TST-002 | The test did not start | No AI model with a card for this board model | Train on Training |
| AOI-TST-003 | The test did not start | The dataset version has no locked validation set | Split and lock it on the Datasets tab |
| AOI-TST-004 | An image was skipped | Refused as in AOI-INSP-001 to -003 | Listed under the table with its code |
| AOI-TST-005 | The export failed | Disk full or folder not writable | Pick another folder |
| AOI-TST-006 | The run was cancelled | — | Partial results shown, not stored as a validation |
| AOI-TST-007 | The validation report cannot be made | The run used a folder, not a frozen dataset version, or no agreement check is stored | Run on a dataset version with an agreement check |

## Requirements served

REQ-TST-001, -002, -003, -004, -005, -006, -007, -008, REQ-TRN-011, REQ-SET-021, REQ-SET-019.

## Rules applied

Role first; verdict first in each row (Pass/Fail and the red row lead to Compare); one blue primary (Run Test);
confirmation only before exporting; busy, progress, time left and Cancel; no dead ends; accuracy claims carry
counts and synthetic runs say "not accuracy"; glossary (Missed defect, False call, Validation, AI model,
Regression set is the fixed folder of boards); sizes; every string through `self.tr()`.

## Decisions (2026-10-02)

- Q45: Keep Accuracy and Precision beside Missed defects and False calls, which lead. Reason: GUI §4.3 lists them; S45 leads with missed-defect and false call rates.
- Q46: Only a frozen version's locked validation set counts as a validation. Reason: REQ-TST-008 and S48 need the locked set and its manifest hash.
- Q47: "95 % upper bound 5.8 %". Reason: REQ-TST-002 and S45.
- Q48: The customer and the AI lead sign the validation report. Reason: REQ-TST-008 and S48.
- Q54: The page stays "AI Model Test" with Run Test and Run Test Again; sentences call a locked-set run a validation and never say "test run"; the Recipe Editor's one-image trial is "Try Recipe…". Reason: GUI §3 and §4.3 name the page and buttons; the Charter's word list puts Validation in place of "test run"; built in #102 and #103.
