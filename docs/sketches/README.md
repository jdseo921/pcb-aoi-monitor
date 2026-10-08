# Screen sketches

The Engineering standard ("Ready before work") says a screen change starts only when it has a sketch. Sketches
live here, one Markdown file per screen change, named `<page>-<topic>.md` (for example
`inspection-run-controls.md`). Jay approves a sketch by merging the pull request that adds it; a stage that
changes a screen cites its sketch in the pull request.

Each sketch holds:

- the page and the roles that see it;
- a wireframe (ASCII, or a hand-written SVG in this folder);
- every control with its label (the Charter's words only), its keyboard key and its size class
  (button at least 120 × 40 px, operator touch target at least 48 px tall, text at least 14 pt, verdict 40 pt);
- the empty state and the next step it offers;
- each error the screen can show, with its `AOI-<AREA>-<NNN>` code (a placeholder until the catalogue exists);
- the requirement IDs the screen serves (`docs/requirements/stage1.md`);
- anything the GUI specification leaves open, marked "Question for Jay".

Rules every sketch follows (Engineering, "Screens"): role first, verdict first, one frame, at most 2 clicks from
Home, no dialog over a dialog, destructive buttons red and never focused by default, every string translatable.

## Stage 1 sketches (stage S02)

Size classes (B, T, T+, F, V) and the shared patterns are defined once in `frame-and-patterns.md`; every other
sketch inherits them. The thirteen sketches arrive in four pull requests (S02a to S02d), each under the Engineering
standard's 400 changed lines, in the order of this table; a link below works once its pull request is merged. Error codes are placeholders (`AOI-<AREA>-0xx`) until the catalogue in #4 exists.

| Sketch | Screen change | Stages it serves |
|---|---|---|
| [frame-and-patterns.md](frame-and-patterns.md) | Shared frame, empty state, error dialog, busy and progress, presenter theme | S14, S17, S18, S54 |
| [home-step-cards.md](home-step-cards.md) | Six step cards with status and the training indicator | S40 |
| [inspection-run-controls.md](inspection-run-controls.md) | Verdict with shape, run controls and keys, view picker, refusals, alarm log, Compare in one click | S14, S18, S23, S24 |
| [compare-decision-table.md](compare-decision-table.md) | Views, decision table from the stored result, plain-language why, try thresholds, Save to Recipe, AI threshold override | S26, S27, S28 |
| [recipe-editor.md](recipe-editor.md) | ROI drawing and editing, ROI fields, Test Run, revisions, AOI checklist with reason prompt, mm scale | S29, S49, S50 |
| [training-import.md](training-import.md) | Import files or ok/ and ng/ folders with view and defect type, progress, refused files | S31 |
| [training-labels.md](training-labels.md) | OK/NG/UNSURE labels with history, defect box editor, second-person check, labeller agreement | S32, S33, S34 |
| [training-datasets.md](training-datasets.md) | Frozen dataset versions with manifest, validation lock, customer and allowed uses | S35, S36, S38 |
| [training-run-and-versions.md](training-run-and-versions.md) | Training run with progress and Cancel, versions, Activate and Roll back, model card, export | S39, S40, S41, S42, S43 |
| [model-test.md](model-test.md) | Test source, rates as n of N with bounds, recall per type, live results, history, exports, validation report | S44, S45, S46, S47, S48 |
| [logs-history.md](logs-history.md) | History table and filters, export with confirmation, archive, Admin-only delete | S51 |
| [settings-demo.md](settings-demo.md) | Workspace, AI device, input limits, demo load and reset, scripted run pace, presenter theme | S53, S54 |
| [profile3d-card.md](profile3d-card.md) | The "Coming in Stage 2" card | S54 |

Sketches still to write before their stages start: the sign-in dialog, user management in Settings and the
first-run wizard (ADR 0002), and the verdict override (REQ-INSP-013).
