# Compare: views and the decision table

Sketch for stage S02; used by stages S26, S27 and S28. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Compare (Production). All roles see the views, the verdict, the decision table and the explanation. The "Try other
thresholds" panel and Save to Recipe exist for Engineer and Admin only; an Operator does not see the panel (role
first: thresholds live on Engineer pages). Opened in one click from an NG or WARN on Inspection, from a row on
Logs & Export, or from the sidebar.

## Wireframe (1920 × 1080; at 1366 × 768 the two images stack and the table scrolls)

```
Compare      Result 2026-10-01 13:33:24 · ng_003.png · AI model v1.2 · Recipe rev 4 · View Top
[Pick Board…] [Last Inspected]   Reference (● Golden board) ( OK sample… )   Show (●Side by side)(Difference)(AI heatmap)(Boxes only)
┌──────── Golden board ────────┐ ┌──────── Test board ──────────┐ ┌──────────────────────────────────────┐
│                              │ │                              │ │ │          ✗   NG                    │ │ V
│   zoom and pan move both     │ │   boxes 1, 2 on the defect   │ │ ┌──────────────┬──────┬──────┬───────┬─────┬──────┐
│   images together (1 px)     │ │   dashed twins on the left   │ │ │ Check        │Source│Value │Thresh.│Rule │Result│
│                              │ │                              │ │ │ AI score     │ AI   │15.72 │ 5.69  │≥ NG │ NG ■ │ red
│                              │ │                              │ │ │ Diff. regions│Golden│ 2    │ 0     │> NG │ NG ■ │ red
└──────────────────────────────┘ └──────────────────────────────┘ │ │ Changed area │Golden│0.14 %│0.50 % │≥ NG │ OK   │
                                                                  │ │ Similarity   │Golden│0.963 │0.800  │< NG │ OK   │
 Why this board is NG (one sentence per failing check):           │ │ ROI R2 Polar.│ ROI  │ 1.9  │ 1.0   │≥ NG │ NG ■ │ red
 • AI score 15.7 is above the threshold 5.69.                     │ │ Alignment    │Golden│ 358  │ 12    │info │ INFO │
 • 2 difference regions were found; the recipe allows 0.          │ │ Time         │System│578 ms│1,000  │< WARN│ OK  │
 • ROI R2 (Polarity) scored 1.9 × its threshold 1.0.              │ └──────────────┴──────┴──────┴───────┴─────┴──────┘
┌ Try other thresholds (Engineer; nothing is saved until Save to Recipe) ───────────────────────────────────────────┐
│ AI threshold  [▢ Override the AI model's value 5.69] [ 5.69 ]   Pixel difference [45]  Min defect size [0.8 mm]  │
│ Similarity minimum [0.80]  Allowed difference regions [0]        Would be: ▲ WARN      [Re-evaluate] [■ Save to Recipe] │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The table comes from the **stored** result, row for row, with the thresholds that applied at the time
(REQ-CMP-003); it never re-inspects on open. Failing rows: NG red #E53935, WARN amber #FDD835 with dark text. The
rows highlighted on arrival from Inspection are the ones that failed (REQ-INSP-009). Views: Side by side,
Difference heatmap, AI heatmap, Boxes only; each renders within 300 ms from the stored maps (REQ-CMP-002).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Pick board | Pick Board… | Ctrl+O | T | Any stored result (history list) or an image file; a file is inspected with a busy banner |
| Last inspected | Last Inspected | L | T | The board shown on Inspection |
| Reference | Golden board / OK sample… | R | T (segmented) | OK sample… lists the board model's OK samples (REQ-CMP-006); metrics recompute with a busy indicator |
| Show | Side by side / Difference / AI heatmap / Boxes only | 1 2 3 4 | T (segmented) | |
| Image views | — | wheel, drag, Home fits | — | Zoom and pan linked within 1 px at 100 % (REQ-CMP-001) |
| Decision table | Check, Source, Value, Threshold, Rule, Result | ↑ ↓ | rows 14 pt | Selecting a row centres the defect it produced, when it has one |
| Why | one sentence per failing check | — | text 14 pt | Names the check, its value and its threshold with units, glossary words only (REQ-CMP-004) |
| AI threshold override | Override the AI model's value | — | F | Engineer; ticking enables the field; clearing restores the calibrated value (REQ-TRN-015) |
| Threshold fields | Pixel difference, Min defect size (mm), Similarity minimum, Allowed difference regions | — | F | Engineer; mm sizes follow the board model's scale (REQ-RCP-006) |
| Re-evaluate | Re-evaluate | Ctrl+R | B | Recomputes from the stored maps within 300 ms, no AI model run; shows "Would be: ▲ WARN" beside the stored verdict |
| Save to Recipe | Save to Recipe | Ctrl+S | B | The page's one blue primary button; confirmation sheet lists before → after, then a new revision with an audit entry (REQ-CMP-005) |

## Empty state

"No board to compare yet. Inspect a board on Inspection, or Pick Board… from the history." with both links. No
Golden board for the board model: "No Golden board for TBOX-A1 yet. Train an AI model on Training." (Operator:
"Ask an Engineer to train on Training.").

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-CMP-001 | This result has no stored heatmaps | It was saved before evidence maps were kept | The decision table still shows; [Re-run] inspects again with the stored recipe revision, busy banner meanwhile |
| AOI-CMP-002 | The boards could not be aligned | Fewer than 12 alignment inliers | Check the view tag and the reference; metrics are shown as INFO |
| AOI-CMP-003 | The file was refused | Same limits as AOI-INSP-001 to -003 | Load an image within the limits |
| AOI-RCP-004 | The recipe was changed by someone else | A newer revision exists | Reload, then save again; nothing was overwritten |
| AOI-USR-0xx | Save to Recipe needs the Engineer role | — | Switch User |

## Requirements served

REQ-CMP-001, -002, -003, -004, -005, -006, REQ-TRN-015, REQ-INSP-009, REQ-INSP-012, REQ-RCP-006, REQ-SET-021,
REQ-USR-001.

## Rules applied

Verdict first (banner, image, checks, metrics in that order; failing rows highlighted); role first (threshold
panel for Engineer and Admin only); one blue primary (Save to Recipe); confirmation only before overwriting a
recipe; no dialog over a dialog (the confirmation is an inline sheet); glossary ("AI score", "Golden board",
"Threshold", "Recipe", "ROI"); busy indicator for any recompute over 1 s; sizes.

## Questions for Jay

- Operators: hide the threshold panel (proposed) or show it read-only so they see what an Engineer can change?
- Names in the table: "Similarity" for SSIM and "Golden" for the compare source; agree, or keep "SSIM" for
  engineers?
- Should Re-evaluate show the would-be verdict beside the stored one (proposed) or replace the banner?
- Pick Board… lists history (proposed); should it also take a file for a board never inspected on this station?
