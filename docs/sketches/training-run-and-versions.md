# Training: run, progress, AI model versions and model card

Sketch for stage S02; used by stages S39 to S43. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Training › Train and Training › AI models (Engineering). Engineer and Admin. The header indicator and the Home
card show a running training on every page (S40, [home-step-cards.md](home-step-cards.md)).

## Wireframe (1920 × 1080)

```
Training   TBOX-A1                                              │ Samples │ Datasets │ Train │ AI models │
┌ Train ────────────────────────────────────────────────────────────────────────────────────────────┐
│ Dataset version [DS-TBOXA1-R3-TOP-v4 ▾]  (frozen versions only; manifest ✓ 44/44)                   │
│ Epochs [60]  Input size [256 ▾]  Seed [1234]  Device CPU (Settings: Auto)  Code 48872d7              │
│ Validation set locked ✓ 50 OK / 1 NG · training set 38 OK · NG used for calibration only            │
│ [■ Start Training]  blue primary                                                                     │
│ Training v1.3 · Training epoch 23 of 60  [████████░░░░░░░░░░░░] 38 % · about 6 min left   [Cancel]  │
│ log: 13:41:02 aligned 38 of 38 · 13:41:50 Golden board built · 13:42:10 epoch 1 loss 0.0412 …       │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ AI models ────────────────────────────────────────────────────────────────────────────────────────┐
│ Version │ Created          │ Dataset              │Threshold│ Missed defects │ False calls │ Card │ State  │
│ v1.3    │ 2026-10-01 13:48 │ DS-TBOXA1-R3-TOP-v4  │ 5.41    │ 0 of 1 (95 %)  │ 1 of 50     │ ✓    │ ready  │
│ v1.2 ●  │ 2026-09-28 10:30 │ DS-TBOXA1-R3-TOP-v3  │ 5.69    │ 0 of 1 (95 %)  │ 2 of 50     │ ✓    │ active │
│ v1.1    │ 2026-09-20 17:05 │ DS-TBOXA1-R3-TOP-v2  │ 6.02    │ 1 of 1         │ 4 of 50     │ ✓    │ —      │
│ [Activate] [Roll Back to v1.1] [Model Card] [Export…]                                                 │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Training runs off the UI thread. Steps shown in the progress bar: Checking the dataset, Aligning images n of N,
Building the Golden board, Training epoch n of N, Calibrating the threshold, Validating, Writing the model card.
Progress and time left update at least every 10 s; Cancel stops within 10 s, deletes the partial version and
keeps the active AI model (REQ-TRN-008). The new version installs inactive with its model card; every version
records seed, code commit, settings and dataset version (REQ-TRN-009).

Model Card view (inline panel, printable): identity (version, board model, dataset version, seed, commit,
settings, who trained it and when), set-up (camera, resolution, scale), rates with counts and 95 % upper bounds
(missed defects, false calls), recall per defect type, time per image on this station, thresholds, known limits,
sign-off lines (AI lead, customer). A version without a card cannot be activated (REQ-TRN-011).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Dataset version | Dataset version | — | F | Frozen versions of this board model and view, newest first |
| Epochs, Input size, Seed | as named | — | F | Defaults from Settings; the seed is random unless typed |
| Start Training | Start Training | Ctrl+T | B | The tab's one blue primary; checks the refusals below first; disabled while a run is on |
| Cancel | Cancel | Esc | B | Beside the bar; confirmation not needed (the active AI model stays) |
| Log | — | — | text 14 pt | Last 200 lines; the full log is in the workspace |
| Activate | Activate | — | B | Blue primary on the AI models tab; refused without a card; at 1.0 it runs the go-live gate (REQ-TRN-012) |
| Roll back | Roll Back to v1.1 | — | B | One click: activates the previous active version and restores its Golden board (REQ-TRN-010); audit entry |
| Model Card | Model Card | — | B | Opens the card panel; [Print…] and [Copy] inside it |
| Export | Export… | — | B | Weights-only .pt plus the model card (JSON and PDF) into one folder; confirmation names the version (REQ-TRN-013) |

## Empty state

Train tab without a frozen dataset: "No frozen dataset for TBOX-A1 yet. Freeze one on the Datasets tab." with
[Open Datasets ›]. AI models tab: "No AI model yet. Start Training from a frozen dataset." with [Open Train ›].
While training: "v1.3 will appear here when training ends."

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-TRN-030 | Training did not start | Fewer than 20 OK images for this board model and view | Add OK boards and freeze a new version |
| AOI-TRN-031 | Training did not start | A locked validation image is in the training set | Freeze a new version; the lock is kept |
| AOI-TRN-032 | Training stopped | Out of memory at this resolution | Lower the input size, or train on a station with more memory; the active AI model is unchanged |
| AOI-TRN-033 | Training failed | Engine error, details in the log | Copy Details; the active AI model is unchanged |
| AOI-TRN-034 | Training cancelled | — | Partial version removed; active AI model unchanged |
| AOI-TRN-035 | Activation refused | The version has no model card | Train again, or wait for the card step to finish |
| AOI-TRN-036 | Export failed | Disk full or folder not writable | Pick another folder |
| AOI-TRN-037 | Training did not start | The dataset belongs to another customer, or the use is not allowed | Pick a dataset of this customer with the allowed use (REQ-TRN-017) |
| AOI-TRN-038 | The AI model file was refused | It needs code to load, or is not weights only | Use a file exported by this app (REQ-TRN-014) |

## Requirements served

REQ-TRN-007, -008, -009, -010, -011, -012, -013, -014, -017, REQ-SET-021, REQ-SET-019.

## Rules applied

Role first; one blue primary per tab (Start Training; Activate); progress, time left and Cancel over 10 s;
confirmation only before exporting; no dialog over a dialog; no dead ends; glossary (AI model, Golden board,
Training, Validation, Missed defect, False call, Threshold); sizes; every string through `self.tr()`.

## Questions for Jay

- Roll back: only to the previously active version in one click (proposed), with Activate for any other?
- Should Engineers set epochs, input size and seed (proposed) or only Admins in Settings?
- Export the model card as JSON and PDF beside the .pt (proposed), or only the PDF?
- Time left before the first epoch: show "estimating…" (proposed) or an estimate from the last run?
