# Inspection: run controls, verdict and alarm log

Sketch for stage S02; used by stages S14, S18, S23 and S24. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Inspection (Production). All roles. The page shows run controls, the verdict, the defects and the alarm log only;
thresholds, ROIs and AI model versions are not on this page for any role. v0.1's "Auto-save each board" box goes:
every result is saved with its evidence before the next board starts (REQ-INSP-008).

## Wireframe (1920 × 1080; at 1366 × 768 the defect table shows 6 rows and the alarm log 3)

```
Inspection                                           Board model TBOX-A1 · AI model v1.2 · Recipe rev 4
[Load Images…] [Load Folder…]   View  (● Top) ( Side) ( Bottom)          Queue 3 of 12 · ng_003.png
┌───────────────────────────────────────────────┐ ┌────────────────────────────────────────────────┐
│                                               │ │ ┌────────────────────────────────────────────┐ │
│                                               │ │ │          ✗   NG                            │ │ V, 40 pt
│         board image, boxes coloured by        │ │ └────────────────────────────────────────────┘ │
│         severity: Critical red, Major orange, │ │ AI score 3.81 × threshold · 1 defect · 578 ms   │
│         Minor amber; label "1 Polarity Error" │ │ ┌────┬────────────────┬───────┬─────┬────┬────┐ │
│                                               │ │ │ No │ Type           │ Score │Side │  X │  Y │ │
│                                               │ │ │ 1  │ Polarity Error │ 3.81  │ Top │183 │187 │ │
│                                               │ │ └────┴────────────────┴───────┴─────┴────┴────┘ │
│                                               │ │ [ Compare › ]  (T; shown for NG and WARN)       │
└───────────────────────────────────────────────┘ └────────────────────────────────────────────────┘
[ ▶ Start  F5 ]   [ ■ Stop  F6 ]   [ ■■ Next Board  F8 ]   [ Save Result  F9 ]          T+, 56 px tall
┌ Alarms ───────────────────────────────────────────────────────────────────────────────────────────┐
│ 2026-10-01 13:33:24  AOI-INSP-011  ng_003.png: NG, 1 defect (Polarity Error, Critical)             │
│ 2026-10-01 13:33:20  AOI-INSP-002  big_board.tif refused: 62 MP is over the 50 MP limit            │
│ 2026-10-01 13:33:12  AOI-INSP-000  12 images loaded from D:\boards\lot-42                          │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Verdict banner (V): colour, word and shape together, white text on green and red, dark text on amber:
`✓ OK` green #43A047, `✗ NG` red #E53935, `▲ WARN` amber #FDD835. Shown within 100 ms of the result; while a board
is being inspected the banner turns grey with a spinner and "Inspecting…" (busy pattern). Order of the right
column: verdict, then the boxes on the image, then the defect list, then metrics (the one summary line).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Load images | Load Images… | Ctrl+O | T | PNG, JPG, BMP, TIFF; refused files go to the alarm log, the rest are queued |
| Load folder | Load Folder… | Ctrl+Shift+O | T | Same limits; sub-folders included |
| View picker | View: Top / Side / Bottom | Alt+V cycles | T (segmented, 48 px) | Tag kept with every result and shown in the Side column and exports (REQ-INSP-010) |
| Start | ▶ Start | F5 | T+ | Green #43A047; runs the queue board after board; disabled while running |
| Stop | ■ Stop | F6 | T+ | Red; stops after the current board; nothing is deleted, so no confirmation; never the default focus |
| Next Board | Next Board | F8 | T+ | The page's one blue primary button; inspects one board; default focus when idle |
| Save Result | Save Result | F9 | T+ | Marks the result as checked by the operator and copies the overlay to the exports folder; the result itself is already saved |
| Compare | Compare › | Enter on the banner, or C | T | One click opens Compare on the stored result with the failing checks highlighted (REQ-INSP-009); hidden for OK |
| Defect row | — | ↑ ↓ | row 48 px | Selecting a row centres its box within 300 ms (REQ-INSP-004) |
| Alarm log | Alarms | — | rows 14 pt | Time (ISO date, 24-hour), code, message; last 1,000 kept across restarts (REQ-INSP-006) |

Every action works by touch and by its key wherever the focus is on the page; each shows a response within
100 ms (the button presses, the banner goes busy).

## Empty state

Image area: "No images loaded. Load Images… or Load Folder… to queue boards. In Stage 2 the camera fills this
view." with the two buttons. No board model: "Pick a board model in the header first." Queue finished: banner
keeps the last verdict, status line "End of queue: 12 boards, 3 NG, 1 WARN. Load more images or export on Logs &
Export ›".

## Errors

Refusals and failures go to the alarm log with their code; only "nothing can run" cases open the error dialog.

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-INSP-001 | A file was refused | It is not an image (PNG, JPG, BMP, TIFF) | Load image files only |
| AOI-INSP-002 | A file was refused | Over 50 MP (proposed) | Resize it, or raise the limit in Settings |
| AOI-INSP-003 | A file was refused | Over 200 MB (proposed) | As above |
| AOI-INSP-004 | A file could not be read | Missing, locked or unreadable | Check the file and load again |
| AOI-INSP-005 | This board model cannot be inspected | No Golden board and no AI model yet | Dialog with "Ask an Engineer to train on Training"; Engineer sees [Open Training ›] |
| AOI-INSP-006 | Inspection of one board failed | Engine error (details in the log) | The run stops; press Next Board to go on, Copy Details for support |
| AOI-INSP-007 | The result could not be saved | Disk full or workspace unwritable | The run stops until space is freed (REQ-LOG-006) |
| AOI-INSP-010, 011, 012 | Verdict OK / NG / WARN | Alarm log lines for every board, so the log reads as a shift record | NG and WARN: press Compare › |

## Requirements served

REQ-INSP-001, -002, -003, -004, -005, -006, -008, -009, -010, -015, REQ-SET-019, REQ-SET-021, REQ-USR-001.

## Rules applied

Role first (no threshold, ROI or AI model control on the page); verdict first (banner 40 pt leads, Compare in one
click); one blue primary (Next Board); short paths (Home → Inspection → Start is two clicks; no dialog over a
dialog; Stop needs no confirmation); no dead ends; sizes (T+ 56 px run controls, 14 pt table); F5, F6, F8, F9;
"AI score", never "anomaly z-score"; every string through `self.tr()`.

## Questions for Jay

- Remove the "Auto-save each board" box and always save (proposed by REQ-INSP-008)?
- Start green and Stop red as in GUI §7, with Next Board as the one blue primary: agree, or make Start primary?
- What does Save Result mean when every result is already saved: operator check mark plus an overlay copy
  (proposed), or should F9 be free for another action?
- Column name "Side" (GUI §4.1) for the Top / Side / Bottom view tag, or rename the column "View"?
- Should an Operator be able to load files at all in G1, or only an Engineer, with the Operator running a queue?
