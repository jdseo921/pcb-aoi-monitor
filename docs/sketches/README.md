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
