# ADR 0014: Master samples at the start of each shift

- Status: Proposed under Jay's instruction of 2026-10-11 ("Make decisions that are the best for industry norm
  standards"; Jay chose "Merge on green", which named this check as the next change). Jay's merge of this record
  accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-INSP-017 (new, MUST G1), Engineering standard "On the line" (MUST), ADR 0013, migration 0024,
  AOI-INSP-016, AOI-INSP-017, setting `shift_check_hours`

## Context

The Engineering standard's "On the line" rule is a MUST: each shift starts by inspecting master samples, a known-OK
board and a known-NG board for each Critical type the recipe checks where samples exist, and production stays blocked
until every verdict is right. This is the norm on production AOI lines. A known-good and a known-bad board run through
the machine at shift start, after a programme change and after maintenance. It catches a changed recipe, a wrong AI
model, a moved Golden board or a broken file before a shift of boards is judged by it. Until now the app had no such
check, so nothing stopped a line from running all shift on an engine that judged a known board wrongly.

In Stage 1 the station inspects image files, not boards under a camera. The master samples are therefore stored images.
They prove that the engine in use still judges known boards right. Lighting and camera drift are checked once the
Stage 2 camera judges the physical master boards.

## Decision

1. **Master samples are picked from the labelled samples, the same ones every shift:** the board model's oldest sample
   labelled OK, and its oldest sample labelled NG of each Critical defect type (the classification table's severity).
   With no Critical NG sample, its oldest NG sample of any type is used. The Golden board's own sample is left out.
   Picking them needs no new screen, and they change only when a label changes.
2. **The check passes only when every verdict is right.** A known-OK board must be judged OK. A known-NG board must be
   judged NG or WARN, as AI Model Test counts it, since WARN also stops the board for a person.
3. **Boards are blocked until a check counts.** Inspection asks before every board, so Start, Next Board and a run in
   progress stop with AOI-INSP-016 until a check passes. A passed check counts for `shift_check_hours` (default 12,
   0 to 24 on Settings), and only while the AI model, recipe revision, Golden board and scale in use are the ones that
   judged it. Any change asks for the check again, as a programme change does on a line.
4. **Shift Check (F7) is on the Inspection page, for every role,** because the operator starts the shift. Each check
   is stored (migration 0024, table `shift_checks`, with what judged it) and audited (`inspection.shift_check`). A
   failed check also stores an NG alarm AOI-INSP-016 and names the sample judged wrongly. A board model with no OK or
   no NG sample cannot run the check (AOI-INSP-017), which says who adds them.
5. **An Admin can set 0 hours to ask for no check,** for a board model still gathering samples. The setting change is
   audited like any other. The demo workspace is loaded with 0, so the scripted run plays at once, and Shift Check
   still works there to show it. Turning the check off at a production station skips a MUST, so that needs Jay's
   approval (CLAUDE.md, rule 2).

## Consequences

- After the upgrade, a station asks for Shift Check before the first board of each board model, so its operators
  need the step in their shift-start routine (operator manual, section 1). A board model with no labelled NG sample
  needs one before the line runs, or an Admin's 0.
- No verdict changes. The check only allows or stops inspection, so the regression set and every stored result stay
  as they are, and no customer notice is needed.
- Not done here: an Engineer choosing the master samples by hand, master samples from a locked validation set, a
  check after a set number of boards, and a check on physical boards with the Stage 2 camera. Each is a follow-up.
