# Training: dataset versions, validation lock, customer and allowed uses

Sketch for stage S02; used by stages S35, S36 and S38. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Training › Datasets (Engineering). Engineer and Admin.

## Wireframe (1920 × 1080)

```
Training   TBOX-A1                                              │ Samples │ Datasets │ Train │ AI models │
┌ Working set ─────────────────────────────────────────────────────────────────────────────────────┐
│ 40 OK · 3 NG · 1 UNSURE · View Top · 3 of 3 NG checked ✓ · 4 of 40 OK checked ✓ (10 %)            │
│ Validation set: split and locked on a frozen version below, never on the working set (S36)        │
│ Customer [Acme Electronics ▾]  Allowed uses [▣ Their own AI models] [▢ Shared improvement] [▢ Demos] │
│                                                                        [■ Freeze Dataset…] blue   │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ Freeze dataset ─────────────────────────────────────────────────────── (inline sheet) ───────────┐
│ Name  DS-TBOXA1-R3-TOP-v4   (board model TBOX-A1, revision R3, view Top, next number 4)             │
│ ✓ every NG label checked   ✓ 10 % of OK labels checked   ✓ customer set                             │
│ ✓ agreement check stored (99 of 100, 27 of 30)                                                      │
│ 44 files · SHA-256 manifest will be written · the version never changes afterwards                   │
│                                                                      [Cancel]   [Freeze]             │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ Versions ─────────────────────────────────────────────────────────────────────────────────────────┐
│ Version              │ Frozen           │ By  │ OK │ NG │ Val. OK/NG │ Customer │ Uses     │ Manifest │
│ DS-TBOXA1-R3-TOP-v3  │ 2026-09-28 10:02 │ kim │ 38 │ 3  │ 50 / 1     │ Acme     │ own      │ ✓ 41/41  │
│ DS-TBOXA1-R3-TOP-v2  │ 2026-09-20 16:40 │ kim │ 30 │ 2  │ 50 / 1     │ Acme     │ own      │ ✗ 1 changed │
│ [Split and Lock Validation Set…] [Verify Manifest] [Open Version] [Export Manifest…]                │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

A version is named `DS-<BOARDMODEL>-<REV>-<VIEW>-v<N>`: board model without hyphens, board revision as entered
with the board model, view, and N counting up per board model and view. Freezing writes the manifest (path,
SHA-256, label, boxes, labeller, checker) and stores customer, allowed uses and the agreement result. Any later
label or file change goes to the working set; the next freeze makes v<N+1> (REQ-TRN-005). A frozen version is
split once, seeded and recorded, into a training set and a locked validation set of at least 50 OK and 30 % of NG
per view, stratified by defect type where possible; the lock is audited and cannot be undone, and a new split needs
a new dataset version (S36). Training refuses a run whose training set holds a locked image, by SHA-256 (REQ-TRN-006).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Customer | Customer | — | F | From the customer profile list; each customer's datasets live in their own encrypted store (REQ-TRN-017) |
| Allowed uses | Their own AI models / Shared improvement / Demos | — | F (check boxes) | Default: their own AI models only |
| Split and lock | Split and Lock Validation Set… | — | B | On a frozen version without a split. Inline sheet: the seed (random, editable), the counts per defect type against "≥ 50 OK and ≥ 30 % of NG per view", [Lock]; audit entry; no unlock (S36) |
| Freeze dataset | Freeze Dataset… | Ctrl+F | B | The tab's one blue primary; opens the sheet; the sheet's Freeze enables only when every line shows ✓ |
| Freeze | Freeze | Enter | B | Writes the version in the background with progress over 10 s; no confirmation (nothing is deleted or overwritten) |
| Verify manifest | Verify Manifest | — | B | Hashes every file off the UI thread, progress and Cancel; result "41 of 41 files match" or the list of changed and missing files |
| Open version | Open Version | — | B | Read-only view of the frozen labels and boxes |
| Export manifest | Export Manifest… | — | B | CSV; confirmation names the file count |

## Empty state

Versions table: "No frozen dataset for TBOX-A1 yet. Check the labels, Freeze Dataset, then split and lock its
validation set." with [Freeze Dataset…]. Working set without samples: "No samples yet. Add OK boards on the Samples
tab." with [Open Samples ›].

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-TRN-020 | The dataset cannot be frozen | n NG labels are not checked by a second person | Samples tab, filter Unchecked |
| AOI-TRN-021 | The dataset cannot be frozen | Fewer than 10 % of OK labels are checked | As above |
| AOI-TRN-022 | The validation set cannot be locked | The frozen version holds fewer than 50 OK or 30 % of NG for this view | Add samples, freeze a new version and split that |
| AOI-TRN-023 | The manifest does not match | n files changed or missing since the freeze | The version is marked; train from another version; Copy Details lists the files |
| AOI-TRN-024 | The dataset cannot be frozen | No customer set | Pick the customer |
| AOI-TRN-025 | The dataset store cannot be opened | Encrypted store key missing or wrong | Check the station's key in Settings (Admin); details in the log |
| AOI-TRN-044 | The dataset store was not changed | The reason names it: no such store, a board model in another store, a key the key store refused, a file that would not go | Do what the reason says, then try again |

## Dataset stores (S38 builds the calls; screens proposed, not built)

Settings › Dataset stores, Admin only. A table of the stores: customer, key id (first 8 hex digits), created, board
models, shredded on. Actions, each an inline sheet, never a dialog over a dialog:

- **New Store…**: the customer (F). On Create the sheet shows the recovery sheet (52 characters in 13 groups of
  four, the store UUID and key id) with Print Sheet…; Close enables once "I have printed it and will keep it apart
  from the station" is ticked, since the sheet is never shown again.
- **Restore Key…**: the 13 groups typed (any case, spaces or hyphens); a wrong sheet says to check each group.
- **Move Board Model In…**: a board model in no store; progress over 10 s with the file count; a move that stopped is
  finished by the same button, which then reads Finish Moving In.
- **Shred Store…**: red, never the primary. The sheet names the customer, the board models and the file and AI model
  counts, says the step cannot be undone and that the sheet's holder destroys the sheet, and enables Shred once the
  customer's name is typed.

Open for Jay: whether the store is picked at a board model's first import (ADR 0010, As built in S38).

## Requirements served

REQ-TRN-004, -005, -006, -016, -017, REQ-SET-017 (UUID per dataset), REQ-SET-021, REQ-SET-019.

## Rules applied

Role first; one blue primary (Freeze Dataset…); confirmation only before exporting; no dialog over a dialog
(inline sheets); progress with Cancel for hashing; no dead ends (each ✗ line in the sheet names the fix);
glossary (Validation, Board model, Master sample is not used here); sizes; every string through `self.tr()`.

## Decisions (2026-10-02)

- Q37: `<REV>` is the board revision entered with the board model ("R3"). Reason: The Charter's glossary: a board model is one PCB design and revision ("TBOX-A1 rev 3").
- Q39: Nobody unlocks a validation set; a new split needs a new dataset version. Reason: S36: locking is audited and cannot be undone (the sketch's Admin unlock and AOI-TRN-026 are removed).
- Q40: [ADR 0010](../adr/0010-customer-dataset-encryption.md) decides: one key per customer store (not per station), in Windows Credential Manager, with AES-256-GCM from the `cryptography` package (a new dependency). Reason: One customer's data can then be shredded alone, and a cipher binding of our own would cost more to trust than three permissive packages.

Still for Jay: Q38, the allowed uses. The three check boxes (default: their own AI models only) stand in until Jay
names the uses the customer contracts allow; that is a contract term, not a screen decision.
