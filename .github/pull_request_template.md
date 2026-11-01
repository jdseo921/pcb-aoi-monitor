<!-- The title carries the requirement or bug ID: [REQ-XXX-NNN] or [#n]. This description is the change note
(CLAUDE.md, "Checklist for every change"), written for an outside reviewer; commits need no checklist. -->

## What changes and why

<!-- The requirement, what the change does, and the plan line it is (docs/plans/2026-11-handover-progress.md). -->

## Evidence

<!-- The test run and its output, the file and line, or the screen, for every claim of done. -->

## Checklist for every change

<!-- State the result of each line: tick it and say how, or mark it n/a with a reason. -->

- [ ] The requirement or bug ID is in the title, and the change traces to a passing test
- [ ] The engine still imports no Qt, and any service API change is typed and documented
- [ ] A schema change ships as a migration, and anything that can change a verdict writes an audit entry
- [ ] Unit, golden-image and screenshot tests pass, and the performance budgets hold
- [ ] Screens are visible only to the roles that need them, meet the size rules, work by touch and keyboard, and route every string through `self.tr()`
- [ ] No new network call without a setting, no secret in code, models load as weights only, and the scans are clean
- [ ] Datasets and models are versioned, carry a model card and pass the go-live gate
- [ ] Every new dependency has an allowed license and a pinned version
- [ ] Docs, the release note and the demo script are updated wherever the change shows
- [ ] A customer notice is drafted if the change can alter a verdict

## Working rules until v0.5.0

- [ ] At most 400 changed lines, generated files not counted, and one concern (size: ...)
- [ ] `tests/regression/expected.json` unchanged
- [ ] Fresh-eyes review by a subagent; every finding fixed or answered below
- [ ] The progress file's line for this PR updated

## Rules applied, assumptions, left undone

## Review findings and answers
