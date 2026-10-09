# Compare: views and the decision table

Sketch for stage S02; used by stages S26, S27 and S28. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Compare (Production). All roles see the views, the verdict, the decision table and the explanation. The "Try other
thresholds" panel and Save to Recipe exist for Engineer and Admin only; an Operator does not see the panel (role
first: thresholds live on Engineer pages; #140, ADR 0006 decision 4). Opened in one click from an NG or WARN on
Inspection, from a row on Logs & Export, or from the sidebar.

## Wireframe (1920 × 1080; at 1366 × 768 the two images stack and the table scrolls)

```
Compare      Result 2026-10-01 13:33:24 · ng_003.png · AI model v1.2 · Recipe rev 4 · View Top
[Pick Board…] [Last Inspected]   Reference (● Golden board) ( OK sample… )
Show (● Side by side) ( Difference ) ( AI heatmap ) ( Boxes only )
┌── Golden board as judged ────┐ ┌──────── Test board ──────────┐ ┌──────────────────────────────────────┐
│                              │ │                              │ │ │          ✗   NG                    │ │ V
│   zoom and pan move both     │ │   boxes 1, 2 on the defect   │ │ ┌──────────────┬──────┬──────┬───────┬─────┬──────┐
│   images together (1 px)     │ │   dashed twins on the left   │ │ │ Check        │Source│Value │Thresh.│Rule │Result│
│                              │ │                              │ │ │ AI score     │ AI   │15.72 │ 5.69  │≥ NG │ NG ■ │
│                              │ │                              │ │ │ Diff. regions│Golden│ 2    │ 0     │> NG │ NG ■ │
└──────────────────────────────┘ └──────────────────────────────┘ │ │ Changed area │Golden│0.14 %│0.50 % │≥ NG │ OK   │
                                                                  │ │ Similarity   │Golden│0.963 │0.800  │< NG │ OK   │
 Why this board is NG:                                            │ │ ROI R2 Polar.│ ROI  │ 1.9  │ 1.0   │≥ NG │ NG ■ │
 • The AI score is 15.72, at or above its threshold of 5.69.      │ │ Alignment pts│Golden│ 358  │ 12    │info │ INFO │
 • The number of difference regions is 2, more than the …         │ │ Time         │System│578 ms│1,000  │< WARN│ OK  │
 • In ROI R2 [Polarity], the AI score is 1.90 × the AI …          │ └──────────────┴──────┴──────┴───────┴─────┴──────┘
┌ Try other thresholds (Engineer; nothing is saved until Save to Recipe) ───────────────────────────────────────────┐
│ AI threshold  [▢ Override the AI model's value 5.69] [ 5.69 ]   Pixel difference [45]  Min defect size [0.8 mm]  │
│ Similarity minimum [0.80]  Allowed difference regions [0]   Would be: ▲ WARN   [Re-evaluate] [■ Save to Recipe]   │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The table comes from the **stored** result, row for row, with the thresholds that applied at the time
(REQ-CMP-003); it never re-inspects on open. Failing rows: NG red #E53935, WARN amber #FDD835 with dark text. The
rows highlighted on arrival from Inspection are the ones that failed (REQ-INSP-009). Views: Side by side,
Difference heatmap, AI heatmap, Boxes only; each renders within 300 ms from the stored maps (REQ-CMP-002).

A muted line under the verdict names the stored result's time, AI model, recipe revision and view, and, when the
board model has moved on, "Since then the board model moved to AI model v1.3 and recipe revision 5." (S26, #130).
The left pane shows the Golden board as judged, even after it changed; when that file changed or is gone, or the
result names none, it says "Golden board not available", why, and offers [Re-evaluate ›] (S26b, #131). The why box
gives one sentence per failing check, NG first, then any check that did not run (#134), e.g. "In ROI R2 [Polarity],
the AI score is 1.90 × the AI model's threshold, at or above the ROI's threshold of 1.00 ×."

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
| Save to Recipe | Save to Recipe | Ctrl+S | B | The page's one blue primary button; confirmation sheet lists before → after and asks for a reason (required), then a new revision with an audit entry of before, after, user and reason (S28, REQ-CMP-005) |

L, R and 1 to 4 act only while no threshold field has focus (frame-and-patterns.md).

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

## Decisions (2026-10-02)

- Q17: Operators do not see the threshold panel. Reason: #140, ADR 0006 decision 4; S28b hides it (#134 had kept it visible until then).
- Q18: The table says "Similarity (SSIM)" and the source "Golden board". Reason: Built at 329f603 (`aoi/ui/pages/compare.py`, CHECK_NAMES and SOURCES): the glossary word first, SSIM for Engineers.
- Q19: "Would be" beside the stored verdict; the banner keeps the stored verdict. Reason: ADR 0006 decision 3 (#140): nothing is stored, so the stored verdict stands.
- Q20: Pick Board… lists stored results and also takes a file, inspected afresh and not stored. Reason: #130 puts the stored-result list with S51; a file is built as "Test Image…" (compare.py at 329f603) for boards never inspected here.
