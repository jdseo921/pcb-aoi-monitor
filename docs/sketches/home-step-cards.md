# Home: step cards with status

Sketch for stage S02; used by stage S40 (training indicator). Frame, size classes, empty-state and error patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Home. All roles. An Operator sees cards 5 and 6 at full size with their buttons; cards 1 to 4 shrink to a status
strip with no buttons ("Set up by an Engineer"), because their pages need the Engineer role. Engineer and Admin
see all six cards with buttons.

## Wireframe (1920 × 1080; 3 × 2 cards; at 1366 × 768 the cards stack 2 × 3)

```
Home   Stage 1: upload → train → tune recipe → validate → inspect → export           Board model TBOX-A1
┌─ 1 Upload samples ───────────┐ ┌─ 2 Train AI model ─────────────┐ ┌─ 3 Tune recipe ─────────────────┐
│ Add OK and NG boards of this │ │ Learn the Golden board and an  │ │ Draw ROIs and set thresholds on │
│ board model and label them.  │ │ AI model from OK boards.       │ │ the Golden board.               │
│ 40 OK · 3 NG · 1 UNSURE      │ │ ⟳ Training running 42 %        │ │ Recipe revision 4               │
│ 2 NG labels unchecked        │ │   about 3 min left · v1.3      │ │ 6 of 10 AOI checks · 4 Stage 2  │
│ [Open Training ›]            │ │ Active AI model v1.2 [Open ›]  │ │ [Open Recipe Editor ›]          │
└──────────────────────────────┘ └────────────────────────────────┘ └─────────────────────────────────┘
┌─ 4 Validate ─────────────────┐ ┌─ 5 Inspect ────────────────────┐ ┌─ 6 Export ──────────────────────┐
│ Test the AI model on the     │ │ Run boards; an NG or WARN      │ │ CSV, overlay images and the PDF │
│ locked validation set.       │ │ opens Compare in one click.    │ │ report for customer validation. │
│ Missed defects 0 of 30       │ │ Today 128 boards · 3 NG ·      │ │ 128 records ready               │
│ False calls 1 of 50          │ │ 1 WARN · last 13:33            │ │ last export 2026-09-30          │
│ [Open AI Model Test ›]       │ │ [■ Open Inspection ›] primary  │ │ [Open Logs & Export ›]          │
└──────────────────────────────┘ └────────────────────────────────┘ └─────────────────────────────────┘
```

Each card: number and name 16 pt, one sentence 14 pt, status lines 14 pt, one link button. Status is read from
the database within 300 ms of Home opening and refreshed every 5 s while the page is shown (REQ-INSP-016).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Card 1 button | Open Training › | Alt+1 | T | Engineer, Admin; opens the Samples tab |
| Card 2 button | Open Training › | Alt+2 | T | Engineer, Admin; opens the tab of the next step: Datasets while no version is frozen, AI models while a trained version waits for Activate, otherwise Train (where a running training shows its progress) |
| Card 3 button | Open Recipe Editor › | Alt+3 | T | Engineer, Admin |
| Card 4 button | Open AI Model Test › | Alt+4 | T | Engineer, Admin; opens the Run tab with the newest dataset version's locked validation set chosen |
| Card 5 button | Open Inspection › | Alt+5 or Enter | T | The page's one blue primary button; default focus for Operators |
| Card 6 button | Open Logs & Export › | Alt+6 | T | All roles (Operators view only) |
| Training indicator | ⟳ Training running 42 % · about 3 min left | — | text | On card 2 and mirrored in the header (S40); click opens Training; when training ends it reads "v1.3 trained, not active" or "Training failed, AOI-TRN-033" until the card is opened |
| Status strip (Operator) | Set up by an Engineer: AI model v1.2 · Recipe rev 4 · validated 2026-09-30 | — | text | Replaces cards 1 to 4 for Operators; no buttons |

Status text per card, when something is missing, is the empty-state sentence below in the card's status lines,
and the button still opens the page.

| Card | Status when done | Status when not done (next step) |
|---|---|---|
| 1 | 40 OK · 3 NG · 1 UNSURE; "2 NG labels unchecked" when a check is pending | "No samples yet. Add at least 70 OK boards." (S58: 50 for the locked validation set and 20 to train, aoi/core/datasets.py; it read 20) |
| 2 | Active AI model v1.2; progress while training | "No AI model yet. Freeze a dataset, then train." |
| 3 | Recipe revision 4 · 6 of 10 AOI checks (4 need Stage 2) | "Recipe uses defaults. Draw ROIs on the Golden board." |
| 4 | Missed defects 0 of 30 · False calls 1 of 50 (counts, never a bare percent) | "Not validated yet. Run the locked validation set." |
| 5 | Today 128 boards · 3 NG · 1 WARN · last 13:33 | "No boards inspected yet. Load images on Inspection." |
| 6 | 128 records ready · last export 2026-09-30 | "Nothing to export yet. Inspect a board first." |

## Empty state

No board model in the workspace: the six cards are replaced by one block, "No board model yet. Create one to
begin." with the button [+ New board model] (T), which focuses the header's + New sheet. Engineer and Admin see it;
an Operator sees "No board model yet. Ask an Engineer to create one." with no button.

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-SET-0xx | The status of a card could not be read | The database did not answer within 1 s | The card shows "Status unavailable, AOI-SET-0xx"; its button still works; Copy Details for support |
| AOI-TRN-033 | Training failed | Shown on card 2 with the one-line reason from the training log | Open Training to read the log; the active AI model is unchanged |
| AOI-USR-0xx | The page needs the Engineer role | An Operator pressed a disabled card | The tooltip "Requires Engineer" is shown; the status bar repeats it |

## Requirements served

REQ-INSP-016 (six cards, one click, status within 300 ms), REQ-TRN-008 (training visible from Home), REQ-SET-018
(one frame, one primary button), REQ-SET-019 (every card's empty state says what to do and links there),
REQ-USR-001 (Operator sees no Engineer controls), REQ-TST-002 (counts, not bare percentages).

## Rules applied

Role first (Operators get run and export cards only); short paths (every Stage 1 page is one click from Home,
and each step's action two, because a card opens the tab of its next step: Freeze Dataset, Start Training and
Activate included). SHOULD skipped, with this reason: Revisions › Open (Recipe Editor) and History › Open (AI Model
Test) take a third click, the tab, because they look back at earlier work and must not hide the step's own tab;
no dead ends (each card's empty status names the next step); glossary words (Board model, AI
model, Golden board, Recipe, ROI, Missed defect, False call, Validation); sizes (T buttons, 14 pt text); every
string through `self.tr()`.

## Decisions (2026-10-02)

- Q5: Operators see cards 1 to 4 as a status strip without buttons. Reason: Role first (MUST) keeps Engineer controls off Operator screens; the strip still shows that the line is set up and validated.
- Q6: Card 2 is "Train AI model". Reason: Charter words (Training, AI model); "Self-train" is not one. Built (#154).
- Q7: Card 5 counts today (local day). Reason: A shift reads today's counts; the whole history is on Logs & Export, one click away.
- Q8: The header indicator shows any long job that continues off its page: training or a batch on AI Model Test. Reason: The busy pattern in frame-and-patterns.md: long work continues when the user changes page, and the header shows it (REQ-SET-021).
