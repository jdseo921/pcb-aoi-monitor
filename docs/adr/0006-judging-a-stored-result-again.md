# ADR 0006: Judging a stored result again

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-02
- Decides: the product owner (Jay), until a tech lead joins
- Related: stage S28a of the Stage 1 plan; REQ-CMP-005, REQ-INSP-012, REQ-USR-001; sketch
  `docs/sketches/compare-decision-table.md`; [ADR 0002](0002-local-sign-in.md) decision 5;
  [ADR 0005](0005-stored-ai-map-format-2.md) (the maps it reads)

## Context

REQ-CMP-005 lets an Engineer try other thresholds on a board already inspected and see the verdict they would give,
within 300 ms at 5 MP and without running the AI model; Save to Recipe then stores them (S28d). Compare reaches the
engine only through `AppContext`, so the service needs one call with a settled contract: what names the result, what
evidence it is judged on, which AI model's calibration applies, who may call it and what it records.

## Decision

1. **`AppContext.re_evaluate(result_uuid, thresholds)`** names the result by the UUID of its record (ADR 0004
   decision 5), and takes the thresholds as a whole recipe of the result's board model, the object the panel edits and
   Save to Recipe stores. Thresholds of another board model are refused with AOI-CMP-005.
2. **The evidence is what was stored.** The checks come from the record, the maps from its files (only those the
   thresholds use), the AI score from its stored AI check, and the AI model's calibration from the registry row the
   record names by UUID, never the active model's: a newer model's calibration was never applied to this board.
3. **Nothing is stored and nothing is audited.** The result is returned to show as "Would be"; the audit trail records
   changes, and Save to Recipe writes the audited revision.
4. **Engineer and Admin only, checked in the service.** ADR 0002 decision 5 checks the role on every write; this one
   call writes nothing but takes the same check (`requires("Engineer", ...)`, AOI-USR-001), since trying thresholds
   is an Engineer's task and a would-be verdict next to a stored one is easy to misread on the line. Compare hides
   the panel from Operators (S28b).
5. **What cannot be judged says so.** AOI-CMP-002 for no such result or no stored decision table, AOI-CMP-003 for a
   map file that is there but cannot be read or is not the map written (ADR 0005 decision 5), and AOI-CMP-004 for a
   map or calibration that a check the thresholds use needs but is gone, naming it; turning that check off lets the
   rest be judged.

## Alternatives considered

- **The integer record id.** Local to one workspace; the UUID still names the record after an export or a merge.
- **The active AI model's calibration.** Simpler, but judges the board by a pixel threshold it was never judged by,
  so the same thresholds would give another verdict after each training run.
- **Any role, as for other reads.** An Operator could produce verdicts the line might act on; the sketch keeps
  thresholds on Engineer pages.
- **Audit every try.** Many entries that change nothing; the change is the saved revision.

## Consequences

- `tests/test_roles_and_audit.py` lists `re_evaluate` as a read that checks the role, so a new read with a role
  check must be listed there too.
- A result whose OK maps the retention sweep deleted can be judged again only with the checks that need them off.
- A result keeps its AI model's calibration after a newer model is made active; a registry row that is gone, or
  damaged by hand, gives AOI-CMP-004.
- Since S29 (REQ-RCP-006) a result also keeps the scale its sizes in mm were applied at, and is judged again at it. A
  result judged before its board model had a scale is judged again at the board model's scale now, which the result
  returned keeps: the scale's counterpart of the active AI model's calibration rejected above, open with Jay.
