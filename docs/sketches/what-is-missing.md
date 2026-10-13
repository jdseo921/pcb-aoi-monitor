# Home and Training: What is missing

Sketch for B3 of the 2026-10 business-readiness brief (F6; REQ-TRN-021; ADR 0022). Frame, size classes, empty-state
and error patterns: [frame-and-patterns.md](frame-and-patterns.md). It adds a list to
[home-step-cards.md](home-step-cards.md) and a tab to [training-import.md](training-import.md)'s page.

## Page and roles

Home, under the six step cards, for every role; Training, its third tab **What is missing** after Samples and
Datasets, for the Engineer and the Admin who open Training. The list is of the board model in the header; with none,
it is not shown (Home shows its empty state, Training its own). An Operator sees Home's list with each button greyed,
its tooltip and a press naming the role the step needs (REQ-USR-001), never hidden.

## Wireframe (1366 × 768, Training › What is missing; Home's list is the same block under the cards)

```
Training  Upload good (OK) and defective (NG) boards; ...                [Samples] [Datasets] [What is missing]
┌─ What is missing ─────────────────────────────────────────────────────────────┐ ┌─ Self-training ──────┐
│ A board model needs at least 70 OK images of one view (20 to train, 50 held   │ │ Dataset version …    │
│ out to test) and 1 or more NG images with every defect boxed; a Validated     │ │                      │
│ version also needs 100 images labelled OK or NG for the agreement check.      │ │                      │
│ Checks  (•) Validated  ( ) Trial: one person, no checks                       │ │                      │
│ ONE-1, Top view: 6 of 10 still missing                                        │ │                      │
│ ✓  OK images                                              80 of 70            │ │                      │
│ ✓  NG images                                              20 of 1             │ │                      │
│ ✓  NG images with every defect boxed                      20 of 20            │ │                      │
│ ○  NG labels checked by a second user                     0 of 20  [Show Unchecked ›]          │       │
│ ○  OK labels checked by a second user (10 %)              0 of 8   [Draw OK Labels to Check]   │       │
│ ✓  Images labelled OK or NG for a calibration set         100 of 100          │ │                      │
│ ○  Agreement check that reached its targets               0 of 1   [Open Labeller Agreement ›] │       │
│ ○  Locked validation set                                  0 of 1   [Freeze Dataset…] greyed    │       │
│    First: NG labels checked by a second user                                  │ │                      │
│ ○  Trained AI model                                       0 of 1   [Start Training] greyed     │       │
│    First: Locked validation set                                               │ │                      │
│ ○  Active AI model                                        0 of 1   [Activate AI Model] greyed  │       │
│    First: Trained AI model                                                    │ │                      │
└───────────────────────────────────────────────────────────────────────────────┘ └──────────────────────┘
```

With **Trial: one person, no checks** picked, the list holds only OK images, NG images, NG images with every defect
boxed, Locked validation set and Trained AI model. Once nothing is missing, a line under the list says so: "Nothing is
missing: ONE-1 has an active AI model.", or for a Trial list "Nothing a Trial version needs is missing. A Trial AI
model does not go live: pick Validated to see what going live needs."

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Tab | What is missing | — | tab | Training's third tab; the list is read again each time it is shown |
| Kind | Validated / Trial: one person, no checks | — | T | The newest version's kind at first, Validated before a freeze; each list (Home's, Training's) keeps its pick while the board model stays |
| Line | ✓ or ○, name, "{have} of {need}" | — | text, 14 pt | ✓ once have reaches need; under a waiting line, muted: "First: {line}" |
| Fix | Add OK Images… / Add NG Images… | — | B | Samples tab, the file picker of that button (Ctrl+O, Ctrl+N there) |
| Fix | Draw Boxes › | — | B | Samples tab, Show NG, the first NG image of the view with no box in the label editor |
| Fix | Show Unchecked › | — | B | Start the Checks: Samples tab with Show Unchecked (ADR 0020) |
| Fix | Draw OK Labels to Check | — | B | As the Samples tab's button: draws 10 % of the OK labels |
| Fix | Open Labeller Agreement › | — | B | Datasets tab, the focus on the agreement's next step (Run Agreement Check, else Label Blind…, else New Set) |
| Fix | Freeze Dataset… | — | B | Datasets tab, the Freeze sheet on the list's view, Trial picked for a Trial list |
| Fix | Split and Lock Validation Set… | — | B | Datasets tab, the Split sheet of the newest unlocked version whose split leaves the 20 OK images training needs |
| Fix | Start Training | — | B | The locked version picked in Dataset version, then Start Training |
| Fix | Activate AI Model | — | B | Activates the newest AI model of the list's kind (Validated list only) |

Each fix button shows only on a line not met; Home's opens Training first. A button is greyed while its line waits for
another (its tooltip repeats the "First:" line) or for a role that may not take the step. Each step waits only for what
it needs: Freeze Dataset… for the images and boxes and, for Validated, the checks and the agreement check; Split and Lock
Validation Set… for nothing; Start Training for the locked set; Activate AI Model for the trained AI model. A press that
cannot act now says why on the status bar (blind labelling open, an import, draw or freeze running, a training run under
way). Once the AI model is there, the line above the list reads "ONE-1, Top view: an AI model is active; 1 of 10 still
missing for a next version" (a Trial list: "a Trial AI model is trained").

## Empty state and errors

No board model: the list is not shown; the page's own empty state offers + New board model. A step a button takes
shows the errors that step shows on Training (for example AOI-TRN-027 on the Freeze sheet, AOI-TRN-045 when training
is refused); the list itself shows none.

## Decisions (2026-10-13)

- Q-B3-1. The NG requirement is 1: the validation set then holds one NG image and an agreement check has one both
  labellers can call NG (ADR 0022, Decision 2).
- Q-B3-2. A Validated list adds a line for the 100 images of a calibration set: 70 OK and 1 NG do not make one.
- Q-B3-3. On Training the list is a tab, not a panel beside the Samples table, which is full at 1366 px (A7).
- Q-B3-4. Counts are of one view (ADR 0022, Decision 5).

Still for Jay: none.
