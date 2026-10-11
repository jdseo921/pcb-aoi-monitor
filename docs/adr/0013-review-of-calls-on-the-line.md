# ADR 0013: Reviewing NG and WARN calls on the line (Real defect or False call)

- Status: Proposed under Jay's instruction of 2026-10-11 ("Make decisions that are the best for industry norm
  standards"; the ask: the app must be ready for workers who aim to minimize false positives). Jay's merge of this
  record accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-INSP-013 (MUST 1.0, brought forward to G1), Engineering standard "On the line" and "Watch and retrain",
  REQ-LOG-001, REQ-LOG-002, migration 0023, AOI-INSP-015

## Context

An AOI station's false calls (a good board called NG or WARN) cost the line more than any other figure: each one is a
board an operator checks by hand, and a line that sees many learns to wave calls through, which is how real defects
escape. Production AOI lines therefore verify every call at a review (verify) station: an operator looks at each
flagged board and classifies it as a real defect or a false call, and the false call rate is tracked per board model
and per programme so engineers can tune the recipe and retrain on the boards that were called falsely.

Until now the app recorded the verdict only. An operator who found a call false had nowhere to say so; the count of
false calls existed only on a validation run (AI Model Test) on a locked set, never on the line. REQ-INSP-013 asked for
an Engineer's override with a reason that keeps the original verdict, for release 1.0.

## Decision

1. Every NG or WARN record can be **reviewed** as **Real defect** (`DEFECT`) or **False call** (`FALSE_CALL`), from
   Inspection (the board just inspected, F10 and F11) and from Logs & Export (the record selected, the same keys).
   A False call needs a reason, picked from five common causes or typed.
2. The verdict the board was given is **never changed**. The review is stored beside it (`review`, `review_reason`,
   `review_by`, `review_time`, migration 0023) and each review, or change of one, writes an audit entry
   (`inspection.review`, before and after). This meets REQ-INSP-013's "keeping the original" and the standard's audit
   rule; it is a disposition, not an override of the AOI's own result, so the regression set and every verdict stay
   as they are.
3. **Any role reviews**, Operators included: the operator at the line is the person who looks at the board, as at a
   review station. The role check stays in the service layer (`@requires("Operator")`), so a later decision to raise
   it to Engineer is one line.
4. The counts show where people look: Home's Inspect card ("False calls n of m reviewed"), the Logs summary line,
   the Logs table's Review column and the CSV export (four columns appended after `ai_check`, so the columns before
   keep their places).

## Consequences

- Engineers see the false calls of a board model on the line, filter them in Logs & Export and open each in Compare to
  tune the recipe or label the image for training; the audit trail shows who called what and why.
- No verdict and no stored result changes, so no customer notice is needed (change control) and the regression set's
  `expected.json` is untouched.
- Not done here: a filter by review in Logs, sending a false call to Training as an OK sample in one click, and a
  drift alarm on the false call rate (Engineering standard, "Watch and retrain", SHOULD). Each is a follow-up.
