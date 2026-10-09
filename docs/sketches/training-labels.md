# Training: labels, defect boxes, second-person check and labeller agreement

Sketch for stage S02; used by stages S32, S33 and S34. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Training › Samples (Engineering). Engineer and Admin. The labeller and the checker are two different signed-in
users; the app refuses a check by the labeller (REQ-TRN-004).

## Wireframe (1920 × 1080; at 1366 × 768 the history panel collapses to a button)

```
Training   TBOX-A1 · 40 OK · 3 NG · 1 UNSURE · 2 NG unchecked · 4 of 40 OK checked      │ Samples │ … │
┌ Samples (filter: All ▾) ───────────────────────┐ ┌ ng_003.png · NG · Top ─────────────────────────────┐
│ ID│Label │Defect types     │View│Labelled│Checked│ │ [Draw Box] Type [Polarity Error ▾] Severity Critical │
│ 43│NG    │Polarity Error ×1│Top │ kim    │  —    │ │ ┌────────────────────────────────────────────────┐ │
│ 42│NG    │Solder Bridge ×2 │Top │ kim    │ lee ✓ │ │ │   image with boxes: selected yellow, saved     │ │
│ 41│UNSURE│—                │Top │ kim    │  —    │ │ │   green; label "1 Polarity Error ◆ Critical"   │ │
│ 40│OK    │—                │Top │ park   │ lee ✓ │ │ │                                                │ │
│ 39│OK    │—                │Top │ park   │  —    │ │ └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘ │ Boxes: 1 Polarity Error (Critical) 183,187 40×32 px  │
[Mark OK] [Mark NG] [Mark UNSURE]   [■ Check Label]  │ [Delete Box] red                                     │
                                                     │ History: 13:21 kim NG Polarity Error (was OK, park)  │
┌ Labeller agreement ────────────────────────────┐ │          12:58 park OK                               │
│ Set [Calibration 100 ▾]  Labellers [kim ▾][lee ▾]│ └──────────────────────────────────────────────────────┘
│ OK/NG agreement 99 of 100 (99 %) ✓ target 98 % │
│ Defect type 27 of 30 (90 %) ✓ target 90 %      │
│ [Label Blind…]  [Run Agreement Check]          │
└────────────────────────────────────────────────┘
```

Labels: OK, NG, UNSURE. UNSURE images are left out of training and validation and appear under the filter
"UNSURE", which [Export List…] turns into a CSV for the customer's quality engineer (REQ-TRN-002). Every NG image
needs at least one box; a box is a position, size, one of the 33 DCT types and the severity the table gives that
type (REQ-TRN-003). Relabelling writes a history line and keeps the old boxes in it.

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Filter | All / OK / NG / UNSURE / Unchecked | — | F | |
| Mark OK | Mark OK | O | B | Selected rows; boxes stay in history |
| Mark NG | Mark NG | N | B | Opens the box editor on the first selected image |
| Mark UNSURE | Mark UNSURE | U | B | |
| Check label | Check Label | Enter | B | The page's one blue primary on this tab; disabled with the tooltip "You labelled this image" for the labeller; records user and time (REQ-TRN-004) |
| Draw box | Draw Box | D | B (toggle) | Drag on the image; Esc leaves the mode |
| Move / resize box | — | drag; arrows 1 px, Shift 10 px | handles 16 px | |
| Type | Type | — | F | 33 DCT types by category; Severity fills from the table and is read-only |
| Delete box | Delete Box | Delete | B | Red, undoable with Ctrl+Z, no confirmation |
| Box list | Boxes | ↑ ↓ | rows 14 pt | Selecting a row selects its box |
| Next / previous image | — | PgDn / PgUp | — | Moves the editor to the next or previous image of the filtered list (S33) |
| History | History | — | text | Who, when, before → after, per image |
| Export UNSURE list | Export List… | — | B | Confirmation names the count (export rule) |
| Agreement set | Set | — | F | A labelled set of 100 images (proposed) |
| Labellers | Labellers | — | F | Two users who each labelled every image of the set blind |
| Blind labelling | Label Blind… | — | B | Shows the set's images one by one with every label, box and history line hidden, and records the user's own labels; the agreement check counts only these (S34) |
| Run agreement check | Run Agreement Check | — | B | Busy indicator; result with counts against 98 % and 90 % (proposed); stored with the next dataset version (REQ-TRN-016) |

O, N, U and D act only while no text field has focus (frame-and-patterns.md).

## Empty state

Box editor on an NG image without boxes: "No defect box yet. Press Draw Box and drag around each defect, then
pick its type." Samples filter with no rows: "No UNSURE images." Agreement panel: "No agreement check yet. Pick a
set of 100 labelled images and two labellers." with the fields focused.

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-TRN-010 | The check was refused | You labelled this image yourself | Ask another Engineer to check it |
| AOI-TRN-011 | The box was not kept | It lies outside the image | Move it inside |
| AOI-TRN-012 | The image cannot be checked | An NG image needs at least one box | Draw a box, or mark it UNSURE |
| AOI-TRN-013 | The agreement check did not run | Fewer than 100 images, or a labeller has not labelled every image of the set | Complete the labels, or pick another set |
| AOI-TRN-014 | The label was not changed | The image belongs to a frozen dataset version | The change goes to the working set; the next freeze makes a new version |

## Requirements served

REQ-TRN-002, -003, -004, -016, REQ-TRN-005 (freeze needs every NG and 10 % of OK checked), REQ-SET-019,
REQ-SET-021.

## Rules applied

Role first; one blue primary per tab (Check Label); destructive Delete Box red, undoable, never default focus;
confirmation only before exporting; no dialog over a dialog (the editor is a panel); glossary (Defect, Severity
Critical/Major/Minor, Validation); sizes; every string through `self.tr()`.

## Decisions (2026-10-02)

- Q33: Every box is one of the 33 DCT types; no "Anomaly". Reason: REQ-TRN-003 and Engineering, Labels (MUST).
- Q34: Any other Engineer or Admin checks a label. Reason: S34: a different user, enforced in AppContext; labelling is the Engineer role (S32).
- Q35: The UNSURE list is a CSV (Export List…), exported by an Admin like every export (Q58 in logs-history.md). Reason: A CSV opens on the customer's PC with no station login; the export rule keeps customer data on the station otherwise.
- Q36: Targets 98 % and 90 % on 100 images until a customer names its own. Reason: S34 and the Engineering standard's proposed values.
