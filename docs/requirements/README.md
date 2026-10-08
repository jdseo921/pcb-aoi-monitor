# Requirements

This folder holds the product requirements of the AOI PoC Inspector. The rules come from the Engineering
standard (Workflow section); this page says how they are applied in this repository.

| File | Holds |
|---|---|
| [stage1.md](stage1.md) | Every requirement that needs no camera: the G1 validation build and the parts of release 1.0 that run on image files |

Stage 2 to 4 requirements (areas CAM, P3D, ROB, MES) follow once the customer's line questionnaire and the
camera shortlist are back.

## One requirement, one row

| Column | Content |
|---|---|
| ID | `REQ-<AREA>-<NNN>`. Areas: INSP inspection, CMP compare, TRN training, TST AI model test, RCP recipe, LOG logs and export, P3D 3D profile, USR users and roles, SET settings, CAM cameras and lighting, ROB robot, MES MES and ERP. An ID is never reused: a dropped requirement stays in its table, marked Withdrawn with the date and the reason. |
| The app shall… | One sentence. |
| Acceptance criteria | What a test checks, with numbers and units. Numbers marked "proposed" are our own starting points until a customer or a test confirms them. |
| Source | Where the requirement comes from (abbreviations below). |
| Priority | MUST, SHOULD or MAY for a named release. |
| v0.1 | Done, Partial or No, checked against commit 364d2c2, saying what is missing. |
| Impacts | What the work touches besides code: Sch schema (ships as a migration), Mdl AI model or model files, Lic new dependency (license check and pinned version), Dem demo script, Doc manual or release notes, Scr screen change (needs a sketch first). "none" when nothing applies. |

Each register file states its stage at the top, and every row in it has that stage. Source abbreviations:
GUI §n is the AOI PoC Software GUI Concept & Functional Specification, RM the Development Roadmap &
Commercialization Plan, DCT §n the PCBA Defect Classification Table, ENG, C&L and LEG the Engineering, Customers &
Launch and Legal & Compliance standards with the section name, Charter the AOI Standards Charter, ADR n a design
record in `docs/adr/`, `#n` a GitHub issue, "resolution test" the
[test record of 2026-10-01](../tests/2026-10-01-resolution-test.md), NIST SP 800-63B-4 the US digital identity
guideline, Jay a product owner request listed below, and "proposed" a rule we suggest that no outside source
states yet.

## Product owner requests

| Date | Request, in Jay's words | Where it was made |
|---|---|---|
| 2026-10-01 | "Essential functions include self-training from sample pcb board image uploads and side-by-side comparisons page that users can optionally access to compare images and see metrics/variables that decide whether an uploaded pcb image has a defect or not." | Jay's first message in the project chat |

## Named releases

| Release | What it is | When |
|---|---|---|
| G1 | The build that runs the customer validation and passes gate G1, the end of Stage 1 | Proposed as 0.3 at the end of November 2026, 8 weeks from 2026-10-01 (RM Stage 1); the schedule itself is still an open Charter decision |
| 1.0 | The first commercial release, assumed here to cover Stages 1 and 2 | 1Q 2027 (RM §3) |

Performance budgets are measured on the reference PC, which is also still open in the Charter.

## Ready before work

A requirement is ready when its ID, source, acceptance criteria and priority are filled in, its impacts are
noted, and a screen change has a sketch. Only a ready requirement gets a GitHub issue (titled with its ID,
labelled `type: feature`, its area, P1 to P3 and the customer) and a branch such as
`feat/REQ-CMP-004-short-name`.

## Tracing

- Pull request titles carry the IDs they implement: `[REQ-INSP-005] feat: run controls by keyboard`.
- Test names carry the ID in lower case: `test_req_insp_005_f5_starts_and_f6_stops`.
- The Engineering standard (Workflow, Traceability) sets the rule: "CI builds the trace matrix on every merge
  from the IDs in pull request titles and test names, and publishes it with each release. A requirement with no
  test, or code with no requirement or bug ID, fails the release gate." The CI job comes with #5.

## Changing a requirement

Change the row in a pull request that says why. The product owner's merge approves it.
