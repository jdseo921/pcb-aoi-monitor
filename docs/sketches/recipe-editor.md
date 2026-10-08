# Recipe Editor: ROIs, thresholds, AOI checks and revisions

Sketch for stage S02; used by stages S29, S49 and S50. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Recipe Editor (Engineering). Engineer and Admin. Operators never see it.

## Wireframe (1920 × 1080; at 1366 × 768 the right column becomes a second tab row)

```
Recipe Editor    TBOX-A1 · revision 4 (unsaved changes ●) · scale 47.6 px/mm  [Calibrate Scale…]
[Draw ROI] Type [Presence ▾]   [Delete ROI] red          │ ROIs │ Thresholds │ AOI checks │ Revisions │
┌──────────────────────────────────────────────┐ ┌───────┬──────────┬──────┬──────┬──────┬──────┬────────┐
│                                              │ │ Name  │ Type     │ X mm │ Y mm │ W mm │ H mm │AI Score│
│   Golden board; saved ROIs green #43A047,    │ │ R1    │ Presence │ 5.3  │ 5.3  │ 2.7  │ 1.5  │ 1.0    │
│   the selected ROI yellow #FDD835 with       │ │ R2 ●  │ Polarity │ 2.3  │ 2.3  │ 2.3  │ 2.3  │ 1.0    │
│   8 drag handles; drag inside to move        │ └───────┴──────────┴──────┴──────┴──────┴──────┴────────┘
│                                              │ Selected ROI R2
│         ┌─ R2 [Polarity] ─┐                  │ Name [R2]  Type [Polarity ▾]  AI Score (× threshold) [1.00]
│         │ ◻     ◻      ◻  │                  │ Height Min / Max mm [—] [—] (Stage 2)  Volume Min / Max mm³ [—] [—] (Stage 2)
│         │ ◻            ◻  │                  │ [▣ Enabled]   [Apply]
│         └─────────────────┘                  │
│                                              │ Test Run: ✗ NG · 2 defects · 578 ms   (checks table below, 5 rows)
└──────────────────────────────────────────────┘
                                                 [Test Run…]                 [■ Save Recipe]  blue primary
```

Thresholds tab: Use AI model ▣ · AI threshold [▢ override 5.69] · Warning band [0.80] · Use Golden board ▣ ·
Pixel difference [45] · Min defect size [0.80 mm] = 38 px ✓ · Similarity minimum [0.80] · Max changed area [0.50 %]
· Allowed difference regions [0]. A size under 4 px shows an amber badge: "0.05 mm is 2.4 px at 47.6 px/mm; the
smallest size the camera resolves is 4 px = 0.08 mm" (REQ-INSP-014, REQ-RCP-006).

AOI checks tab, the 10 mandatory checks (DCT §4): Missing Component ✓ ROI R1 · Misalignment • whole board ·
Polarity Error ✓ ROI R2 · Solder Bridge ○ not covered · Tombstone • whole board · Cold Joint • whole board ·
Shield Can Gap ◌ Stage 2 · Connector Pin Height ◌ Stage 2 · 3D Coplanarity ◌ Stage 2 · Solder Volume ◌ Stage 2.
"• whole board" means the AI model and Golden board comparison cover it without an ROI.

Revisions tab: Revision | User | Saved | Changes (before → after) | [Open] opens it read-only beside the current
one; [Restore as New Revision] copies it into a new revision after the usual confirmation.

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Draw ROI | Draw ROI | D | B (toggle) | Drag on the image draws a box of the chosen type; Esc leaves the mode |
| ROI type | Type | — | F | Presence, Polarity, Solder Bridge, Height, Anomaly (REQ-RCP-002) |
| Move / resize | — | drag; ← ↑ → ↓ 1 px, Shift 10 px | handles 16 px | Selected ROI yellow, saved green; a changed ROI is yellow-dashed until saved (REQ-RCP-001) |
| Delete ROI | Delete ROI | Delete | B | Red; undoable with Ctrl+Z, so no confirmation |
| Undo / Redo | — | Ctrl+Z / Ctrl+Y | — | Every edit before Save is undoable |
| Selected ROI form | Name, Type, AI Score, Height Min/Max, Volume Min/Max, Enabled, Apply | — | F, B | Height and Volume stored now, checked from Stage 2 |
| Calibrate scale | Calibrate Scale… | — | B | Inline sheet: click two points on the Golden board, enter the distance in mm; stores px per mm per board model (REQ-RCP-006) |
| Thresholds | as listed above | — | F | mm fields show their px value at this scale beside them |
| Test Run | Test Run… | Ctrl+T | B | Picks an image (default: last inspected board); runs off the UI thread with a busy indicator; shows verdict, defects and the checks table; stores nothing (REQ-RCP-003) |
| Save Recipe | Save Recipe | Ctrl+S | B | The one blue primary; confirmation sheet lists before → after and asks for a reason when a Stage 1 AOI check is uncovered; creates revision n+1 with user, time and audit entry (REQ-RCP-004, -005) |
| Revisions | Open, Restore as New Revision | — | B | Never overwrites |

## Empty state

Image area without a Golden board: "No Golden board for TBOX-A1 yet. Train an AI model on Training, or set a
Master sample there." with [Open Training ›]. No ROI yet: the ROI table shows "No ROIs yet. Press Draw ROI and
drag on the board; the AOI checks tab shows what each ROI covers." No scale: the header reads "scale not set,
sizes in px" with [Calibrate Scale…].

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-RCP-001 | ROIs cannot be drawn | No Golden board yet | Open Training |
| AOI-RCP-002 | The ROI was not applied | It lies outside the board image | Move it inside |
| AOI-RCP-003 | The recipe was not saved | Role is not Engineer or Admin | Switch User |
| AOI-RCP-004 | The recipe was not saved | A newer revision was saved meanwhile | Reload; your changes are kept as unsaved |
| AOI-RCP-005 | Sizes are shown in px | The board model has no scale yet | Calibrate Scale… |
| AOI-RCP-006 | The Test Run image was refused | Same limits as AOI-INSP-001 to -003 | Pick another image |
| AOI-RCP-007 | Warning: the minimum defect size is under 4 px | Below what the camera resolves | Raise the size or use a higher resolution; saving is allowed, the warning is kept with the revision |

## Requirements served

REQ-RCP-001, -002, -003, -004, -005, -006, REQ-INSP-014, REQ-TRN-015, REQ-SET-021, REQ-SET-019.

## Rules applied

Role first; one blue primary (Save Recipe); destructive Delete ROI red, never default focus, undoable; confirmation
before overwriting a recipe (a save is a new revision, confirmed with before → after); no dialog over a dialog
(calibration and confirmation are inline sheets); busy indicator for Test Run; glossary (Recipe, ROI, Golden board,
Master sample, Threshold, AI model); sizes; every string through `self.tr()`.

## Questions for Jay

- Save without a scale: allow with sizes in px and an amber badge (proposed), or block until calibrated?
- Minimum defect size per customer: one value per board model in the recipe (proposed) or per ROI as well?
- Test Run on the last inspected board by default (proposed) or always ask for a file?
- "Restore as New Revision" for old revisions: wanted at G1, or view-only until 1.0?
