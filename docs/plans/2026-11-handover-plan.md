# Handover plan: from Jay's repository to a factory that inspects boards with it instead of with people

**Owner:** Jay, working alone, with Claude Code as implementer. **Parties:** Jay (vendor) → the company (integrator and first-line support) → the factory (end user, whose inspectors the program replaces). **Baseline:** `b5bf413` (2026-10-14). **Spec of record:** `docs/requirements/stage1.md` (101 rows). **Engineering detail:** `docs/plans/2026-11-production-plan.md` (the PR tables for Stages 1 to 3 remain valid; this plan reorders them around the gates and adds what handover needs). **Governing documents:** `CLAUDE.md` and the four AOI Standards, copied into `docs/standards/` in Gate 0.

Commit this file as `docs/plans/2026-11-handover-plan.md`. Every Claude Code session starts by reading it and `docs/plans/2026-11-handover-progress.md`.

---

## 1. What is true today, said plainly

1. **No real board has ever been inspected by this program.** Every verdict, threshold, screenshot and accuracy-shaped number in the repository comes from boards drawn by `tools/make_synthetic_dataset.py`. The machinery to measure on real boards exists and is good (locked validation set, Trial and Validated versions, the validation report with counts and 95 % bounds, the go-live gate, the on-line review of false calls); the data and the run do not.
2. **The program cannot yet take boards from a line.** Inspection starts when an operator presses Load Folder and Start. A factory needs images to arrive and results to leave without a person: a watched input folder and a result file per board at minimum, cameras (Stage 2) at best.
3. **Anyone at the station can be Admin without a password** and can delete records. A quality instrument whose audit trail names roles rather than people is not acceptable to a factory's quality system, and the threat model says so (row 56).
4. **26 % of the user interface is in Korean** and the Language setting does nothing. Operators who are asked to trust a screen instead of their eyes must read it in their language.
5. **Left running, a station fills its disk in about a week, carries a version number that has not changed across five schema migrations, and fails silently** (the review of 2026-11-01). None of this is architectural; all of it must be fixed before a factory runs it unattended.
6. **Replacing human inspection is a process change, not an installation.** Every AOI deployment in the industry goes through a shadow period (the machine and the people both inspect, verdicts are compared), then review-only (people look at what the machine calls NG or WARN), then unattended with sampled audits. This plan builds the software for each step and names the measured criterion that moves the factory to the next.

## 1a. What the three source documents say about this use

None of them describes handing Stage 1 software to a factory to replace its inspectors; all three put that in Stage 2, after a customer validation. Read for this purpose:

| Document | What it says | How close to "replaces the inspector" |
|---|---|---|
| Roadmap & Commercialization Plan | Stage 1 (8 weeks) is "image upload AI learning and customer validation"; Stage 2 (8 weeks) is camera integration and "real PCB inspection validation"; the "official product release" of 1Q 2027 with 5 to 10 licences at one customer is Phase 1 complete, both stages | Closest in intent: it is the only document that speaks of customers and licences, and its product is Stage 1 plus Stage 2 |
| PCBA Defect Classification Table | A mandatory AOI set of ten defects; four of them (Shield Can Gap, Connector Pin Height, 3D Coplanarity, Solder Volume) are marked side-view or 3D AOI | Closest in scope: it is the list the factory will hold the program to, and it says that 2D photographs cannot cover the whole set |
| GUI Concept & Functional Specification | "A standalone QC cell, independent of SMT lines"; Stage 1 "validate AI model using existing PCB photos, deliver trained AI model and report to customer"; acceptance: verdict within 1 s, 8-hour stability, exported reports verified | Closest in the shape of the station; its Stage 1 is a proof of concept by its own words |

The consequence for this plan: Stage 1 software can replace an inspector only where (a) the factory already has an imaging station that produces photographs the program can watch (D9), and (b) the defect types in scope are the ones validated on that factory's boards at G2, which excludes the four 3D and side-view defects until the company's Stage 2 project. G0 writes both limits into the scope document so no party believes otherwise.

## 2. The gates

Each gate is a document the named parties sign, with evidence attached. Nothing moves to a later gate until the earlier one is signed. Software work is organised so that the earliest gates need the least of it.

| Gate | What is signed | Who signs | Software needed | Calendar driver |
|---|---|---|---|---|
| **G0 Scope** | What "replaces the inspector" means for this factory: the defect list, the minimum defect size, the acceptance targets, how images arrive, how results leave, who looks at WARN, the shadow period's length and exit criteria, the station PC, the support model, what the company receives (binary or source, licence terms, model ownership) | Jay, company, factory | None; a document, plus the decisions in section 3 | One meeting and a week of answers |
| **G1 Safe to run** | The station runs unattended for a month without filling its disk, losing its identity or failing silently; accounts have passwords; images arrive and results leave without a person; the build is signed, versioned and verifiable offline | Jay (release gate record) | Stage 1 of the production plan, plus accounts, line adapter, licence and EULA, Korean for the operator's screens | 6 to 8 weeks of Jay's review time |
| **G2 Validated** | The customer validation report on the factory's own boards: missed defects and false calls as counts with 95 % bounds, on a locked set the model never saw, per defect type, against the G0 targets, signed by the factory's quality lead and the AI lead (Jay) | Jay, factory | Nothing new; the report exists (REQ-TST-008). Needs the factory's images | Depends entirely on when the factory delivers photographs: at least 70 OK boards per board model and view, and every NG example they have, each with its defect type |
| **G3 Handover (the milestone)** | The company accepts Stage 1: every box in section 2a is checked with its evidence; installer and release kit, manuals in both languages, the commissioning checklist, the support runbook, the training session, the acceptance protocol run on the company's own PC and passed | Jay, company | G1, then Stages 2 and 3 of the production plan (the boxes), then the package | 14 to 18 weeks of Jay's review time after G0, in total |
| **G4 Shadow** | The station ran beside the human inspectors for the agreed period; the comparison report shows escapes and false calls against G0 targets; thresholds were tuned and re-validated where needed; the drift monitor stayed within limits | Company, factory | Shadow-mode comparison report (new, small); everything else exists | The period agreed at G0; four weeks is usual |
| **G5 Review-only** | People look only at NG and WARN; OK boards pass on the machine's verdict; the master-sample check runs every shift; sampled audits of OK boards at an agreed rate show no escape above target | Company, factory | Sampled-audit mode (new, small) | A further agreed period |
| **G6 Unattended with audits** | WARN goes to a review station; OK and NG are acted on by the line; audits continue at the agreed rate; model changes go through the go-live gate and a re-validation; a support contract is in force | Company, factory | None new; a procedure | Ongoing |

**The milestone is G3: Stage 1 handed to the company safely.** Jay's handover boxes (section 2a) are its acceptance criteria, so the engineering stages that make the codebase ownable by someone else (Stage 2 "human-sized" and Stage 3 "service boundary" of the production plan) come **before** G3, not after. G2 (validation on the factory's boards) runs in parallel as soon as the factory delivers photographs, and must also be signed before G3, because a handover of software that has never judged a real board is not a safe handover. G4 to G6 are the factory's steps after the milestone.

Order of work, then: G0 → G1 → Stage 2 → Stage 3 → G3, with G2 whenever the images arrive. About 70 to 90 engineer-days of Jay's review time; at four focused hours a day, 14 to 18 weeks. Section 2b says what to cut if that is too long.

## 2a. The handover boxes, translated into things a company can check

Jay's list, box by box: what it means on an offline inspection station (not what it means for a web service), the deliverable that checks it, where it is built, and the evidence the company sees. Where the box's usual meaning would harm the station, the translation says so.

| Box | On this product it means | Deliverable | Built in | Evidence the company checks |
|---|---|---|---|---|
| **Production-ready engineering**: resilient, enterprise-grade, safety over quick hacks | Runs unattended for a month; fails loudly, never silently; every verdict carries its evidence; nothing changes a verdict without an audited, re-validated change | Disk guard, evidence policy, retention, heartbeat and self-check, crash record, version discipline, accounts, licence, regression set byte-identical | G1 | 72-hour synthetic line run in the nightly; the station checks on the reference PC; the release-gate record; `tests/regression/expected.json` unchanged since `b5bf413` |
| **Clear service boundaries**: frontend, backend services, database strictly decoupled | HMI (PySide6 pages) → one typed, versioned API → engine (services, jobs, pipeline) → data layer (SQLite + files). Pages reach no engine code and no SQL; the engine imports no Qt; the cycle a camera will drive lives in the engine | `InspectionCycle` in `aoi/core/cycle.py`; `aoi/core/services/` as eight concern modules behind one facade; typed results for every service method; `test_layers` extended to forbid executable engine imports from pages | G1 (cycle), Stage 3 (the rest) | `tests/test_layers.py` green with the new rules; `ANN401` on; zero string-key subscripts on service results in `aoi/ui`; `docs/API.md` listing every service method with its typed result |
| **Scalable infrastructure**: increased load, intuitive for other engineers | Four axes, each measured: boards per hour (verdict within 1 s and the pipeline off the UI thread, on the reference PC); records (100,000 inspections listed within budget, already tested); stations (one profile configures fifty; release kit and inventory); stages (file, camera, robot, MES as adapters to one cycle). **Not** horizontal scaling of a server: there is no server on the station | Performance budgets recorded on the reference PC; the settings profile (REQ-SET-014); the release kit and `inventory.ps1`; the adapter interface of `InspectionCycle` with `FolderWatch` as its first production adapter | G1, Stage 3 | `perf.json` from the reference PC; fifty synthetic stations configured from one profile in a test; the kit verified on a clean VM; `FolderWatch` and the Inspection page both driving the same cycle in tests |
| **Full-stack professionalism**: robust schemas and clean patterns for frontend, backend, database, APIs, microservices | Schemas: SQLite under numbered, checksummed migrations with a populated upgrade matrix from every shipped baseline; `settings.json` with a schema version; the result file and the input-file naming contract as documented JSON schemas. APIs: the typed service contract, in process now, over local IPC in Stage 4. **Microservices: none on the station.** One engine service plus adapters; the fleet server is the second service, later, off the station. A company that insists on microservices on a factory PC should be told why not, in writing | Migration matrix with fixture databases; `docs/schemas/` (result file, input naming, settings, profile); `docs/API.md`; the page pattern (`run_named`, one worker implementation) | Stage 3 | CI upgrades every shipped baseline; the JSON schemas validate the files the line adapter writes and reads; one worker pattern in `aoi/ui` |
| **Trusted deployment**: CI/CD, safe predictable releases | CI already strong (hash locks, SBOM, provenance, install-self-test-uninstall on every build). "CD" on an offline station is a signed release kit the company installs and verifies without Jay, an upgrade that keeps data, a rollback that is one step, and an acceptance protocol; **not** automatic deployment | Version discipline; signed builds named as such; the release kit with `verify.ps1`; one-step rollback; the release runbook as a checklist; the acceptance protocol | G1, Stage 3, G3 | The company runs the acceptance protocol on its own PC and signs it; a rollback from `v0.4.1` to `v0.4.0` and forward again in that protocol |
| **Production-grade monitoring**: logging, metrics, alerting | Logging: structured JSON lines with rotation and retention (exists, needs rotation). Metrics: a heartbeat file every minute and hourly counters (boards, NG, false calls after review, p50 and p95 verdict time, free disk) written where the company's own monitoring can read them, plus an export when a network exists. Alerting: on-station alarms with codes on the screen and in the log, the drift monitor, the shift master-sample check, and a `alerts.jsonl` the company's tools can tail. **Not** Prometheus or an agent on the station; the fleet server collects later | PRs 1.3 to 1.6 of the production plan; `docs/operations/metrics.md` naming every field; the support bundle | G1 | A reviewer agent reads the heartbeat and alert files from a 72-hour run and answers "is the station healthy, and why not" without the source |
| **Comprehensive testing**: unit, integration, end-to-end | The suite exists (1,009 tests, 83 % behavioural). What is missing for the box: a layered layout anyone can navigate, a 12-minute pull-request run, measured UI coverage, an upgrade test from each shipped database, a real-photo smoke set, and the end-to-end line run through the input folder | Stage 2 restructure; `tests/README.md`; coverage of `aoi/ui` measured; the migration matrix; a five-board real-photo set (from the factory, with permission) run nightly through import, train and inspect; the 72-hour line run | Stage 2, Stage 3, G1 | `pytest tests/unit tests/service` under 5 minutes; pull-request CI about 12 minutes per OS; the nightly green; `tests/README.md` names every layer and fixture |
| **Technical documentation**: API contracts, architecture, onboarding | `docs/API.md` (every service method, its roles, its typed result, its errors); `docs/ARCHITECTURE.md` restructured with a data-model diagram and an inspection sequence diagram; `docs/MAP.md`; `CONTRIBUTING.md`; `tests/README.md`; the manuals; the runbooks; the Standards in the repo | Stage 2, G3 | A reviewer agent given only the documentation lands a one-line change with green CI in one session, and installs a station from the kit using only the commissioning checklist |

## 2b. If 14 to 18 weeks is too long

The boxes cannot be checked faster by working faster; review time is the bound. They can be checked for a smaller promise. Two honest cuts, in order of preference:

1. **Binary handover first, source later.** Hand over signed binaries, the kit, the documentation and support after G1 + G3-package (about 7 to 9 weeks), with Stages 2 and 3 completed before source leaves escrow. The company can run the station; it cannot yet own the code. The boxes "service boundaries", "full-stack professionalism" and "comprehensive testing" are then checked at the source handover, and the G3 document says so.
2. **Narrow the stage.** Hand over a Stage 1 station for a named board model and the defect types that passed G2, with the line adapter and the review station, and leave Stage 2 hardware to the company's project. This is already what the plan does; saying it in the contract removes the expectation that Stage 1 covers the mandatory set.

What should not be cut: G1 (safe to run and accountable), G2 (validated on their boards), the acceptance protocol, and the shadow period.

## 3. Decisions to take at G0 (they become ADR 0024)

The first eight are the production plan's; the rest are new and are the factory's and the company's as much as Jay's.

| # | Decision | Recommended default |
|---|---|---|
| D1 | Evidence policy per inspected board | NG and WARN: full-resolution overlay and maps, kept for the retention the factory names (default 2 years). OK: JPEG overlay at quality 90 plus a preview, maps 7 days. **The factory may require full resolution for every board; then the station gets the disks for it.** |
| D2 | Feature freeze until `v0.5.0` | Yes, with the handover items in this plan as the only exceptions |
| D3 | Accounts with passwords (REQ-USR-002 to -006) | **Before G1, not optional.** The audit trail of a quality instrument names people |
| D4 | Dataset-store encryption | Keep as the vendor-laptop control; BitLocker is the station's disk control; say so in ADR 0010 |
| D5 | IPC wording for Stage 4 | Amend REQ-SET-003 when Stage 4 starts |
| D6 | Trace gate scope | PR title only |
| D7 | Korean | **Operator-facing screens, alarms and the errors an operator can see: before G1.** Engineer and Admin screens: before G3 if the company's engineers are Korean, else with Stage 3 |
| D8 | Reference PC | Before `v0.4.0` is tagged |
| D9 | **How images reach the station** | (a) A watched input folder fed by the factory's existing imaging station, with a file-naming contract (board ID, view, time); (b) Stage 2 cameras integrated by the company; (c) an operator loads folders by hand, which does not replace anyone. Default: (a) now, (b) as the company's Stage 2 project |
| D10 | **How results leave the station** | A result file per board in an output folder (JSON and a one-line CSV: board ID, verdict, time, model version, recipe revision, defect list) within one second of the verdict, plus the end-of-shift CSV. PLC or light-tower signals are Stage 3; MES is Stage 4 |
| D11 | **Who looks at WARN**, and what happens to NG | A review station with the Review function (Real defect, False call); NG boards go to the factory's existing rework flow with the overlay printed or shown |
| D12 | **Acceptance targets** (the Charter's open question) | Per defect type, as counts: missed-defect rate at most X % with an upper 95 % bound at most Y %, false-call rate at most Z %, on at least N locked boards. The factory names X, Y, Z and N; Customers & Launch holds the proposal. **Without numbers signed at G0, G2 cannot be passed or failed** |
| D13 | **Shadow period** | Four weeks or 2,000 boards, whichever is later; exit when the comparison shows escapes under the G0 target with the bound, and false calls under target after tuning |
| D14 | **Sampled audit rate at G5 and G6** | One OK board in 50 to a human at G5, one in 200 at G6, adjusted by the drift monitor |
| D15 | **What the company receives** | Default: signed binaries, the release kit, documentation, training and a support contract; source in escrow. If source is handed over, Stages 2 and 3 of the production plan become gates for the handover |
| D16 | **Licence and term** | REQ-SET-010 (offline licence key bound to the station) and REQ-SET-022 (EULA in the installer) before G3; perpetual per station plus maintenance, or subscription, per the Charter's open business decision |
| D17 | **Who owns the trained AI model and the factory's images** | Licensed to the factory for their own boards; images stay on their station; the Legal & Compliance standard holds the clause. Written into the G0 document |
| D18 | **Support model** | The company is first line with the support bundle and the runbook; Jay is second line; response times named; what the company may change (thresholds, recipes, users) and what it may not (model files, migrations) |
| D19 | **Minimum defect size and the defect list** (REQ-INSP-014) | The factory names the smallest defect the program must find, in millimetres, per defect type from the mandatory set; the camera resolution and the AI input size are chosen from it, not the other way round |

## 4. The software work, by gate

Effort is engineer-days of Jay's review plus Claude Code's typing; the production plan's rule of one PR train a day and 400 lines per PR stands.

### G0: nothing to build. Write and sign the scope document; copy the Standards and this plan into the repo; ADR 0024; register rows (section 5). 3 to 4 days.

### G1: Safe to run, accountable, on the line (30 to 38 days, tag `v0.4.0`)

| PR group | Scope | Register | Days |
|---|---|---|---|
| Production plan PRs 1.1 to 1.10 | Disk guard, evidence policy, retention on a timer, heartbeat and self-check, crash record, support bundle and About, workspace guards, signing hygiene, release kit and runbook, release | REQ-LOG-006, -007, -010, REQ-SET-011, -023 to -027 | 10 to 12 |
| Production plan PR 0.4 | Version discipline, VERSIONINFO, signed-build naming | REQ-SET-023 | in the above |
| **Accounts (D3)** | Argon2id passwords for Engineer and Admin; Operator picks a name with an optional PIN; lockout after repeated failures; idle sessions end; the first Admin is created in the first-run guide with a one-time recovery code; an Admin adds, disables and resets users; the audit names the person. Migration for the users table; the three seeded accounts become a first-run step | REQ-USR-002, -003, -004, -005, -006 | 5 to 6 |
| **Line adapter (D9, D10)** | A `FolderWatch` frame source: the station watches an input folder, inspects each new file once it is complete, moves it to `done/` or `failed/`, and writes a result file per board to an output folder within 1 s of the verdict; a file-naming contract (board ID, view, time) documented and validated; the Inspection page shows the line running and lets an operator pause; `InspectionCycle` is extracted first (production plan PR 3.1) because the watcher and the page are its two drivers | new REQ-INSP-020, -021 | 6 to 8 |
| **Korean for the operator (D7)** | `QTranslator` installed and `.qm` shipped; Home, Inspection, Compare's operator view, the header, the alarm list, every error an Operator can see, and the first-run guide translated with the Charter glossary; a review table for Jay; Korean screenshots of those pages | REQ-SET-006 (operator scope) | 4 to 5 |
| **Licence and EULA (D16)** | An offline licence key signed by Jay, bound to the station's machine ID, checked at start with a plain message and a grace period; the EULA page in the installer; About shows the licence | REQ-SET-010, -022 | 3 to 4 |
| **Station hardening** | Autostart at logon with restart on failure; a kiosk guidance page in the install guide; the start-up self-check from PR 1.4 alarms when the licence, the store key or the input folder is missing | REQ-SET-024 | 2 |
| Release 0.4.0 | Notes in two files, gate record, register status, tag; the station checks run on the reference PC (D8) and recorded | — | 1 |

G1 is signed when: the nightly 72-hour synthetic line run (one board per 10 s through the input folder) holds disk under the policy with the heartbeat present every minute and no silent failure; the station checks pass on the reference PC; `verify.ps1` passes on a clean VM; an Operator-role walkthrough of the Korean screens by a native reader finds no English on the operator path.

### G2: Validated on the factory's boards (no new software; 5 to 8 days of Jay's time per board model)

1. The factory delivers, per board model and view: at least 70 OK boards photographed as they will be on the line (same camera, distance, lighting), and every NG example they have, each with its defect type. More NG boards narrow the bound: with 0 missed of 11 the worst case is 23.8 %; with 0 of 30, 9.5 %; with 0 of 60, 4.9 % (`docs/demo/for-clients.md`).
2. An engineer (Jay, or the company's after G3) imports them, draws the defect boxes, has a second person check the labels, runs the agreement check, freezes and locks a Validated version, trains, and runs the validation on the locked set. This is the Validated path the software already enforces; Trial is not acceptable for G2.
3. The validation report (REQ-TST-008) is produced, with counts, bounds and every miss and false call shown, and compared with the D12 targets. Thresholds may be tuned on Compare and the validation re-run; the report records every run.
4. If the targets are not met, the options are more NG samples, a higher AI input size (ADR 0012), a recipe with ROIs for the failing defect types, or a narrower scope at G0. The report says which, honestly; the program is not handed over for defect types it did not meet.
5. The factory's quality lead and Jay sign the report. The signed PDF and the frozen dataset manifest go into the handover package.

### G3: Handover package (12 to 16 days, tag `v0.4.1`)

| Item | Content | Days |
|---|---|---|
| **Commissioning checklist** | Per station: PC checks, install from the kit, licence, workspace folder and disks, input and output folders and permissions, accounts created, board model and recipe imported, master samples placed, self-check green, first ten boards inspected, sign-off line | 1 |
| **Manuals** | Operator (shift start with master samples, the running line, what an alarm means and what to do, NG and WARN handling, the review station), Engineer (recipes, thresholds, Compare, training a new version, validation, the go-live gate, drift alarms), Administrator (users, backup and restore, upgrade and rollback, the support bundle, retention and disks, the licence); each in English and Korean; each tested by a reviewer agent that follows it on the build | 5 to 6 |
| **Support runbook** | Symptom or error code → meaning → action → what to collect; the support bundle; escalation from the company to Jay; the known-issues list; what the company may change | 2 |
| **Acceptance protocol** | A script the company runs on its own PC: install from the kit and verify; create accounts; run the demo; import the factory's validation set and reproduce the G2 report's counts; run the line adapter for one hour from a replay folder; pull the power once mid-run and restart; produce a support bundle; roll back one version and forward again. Pass criteria for each step | 2 to 3 |
| **Training** | One day: operators (half a day with the demo and their own boards), engineers and the administrator (half a day with the manuals); recorded; the demo kit updated for their boards | 1 to 2 |
| **Production plan Stage 2 documentation items** | `CONTRIBUTING.md`, `tests/README.md`, `docs/MAP.md`, the architecture document restructured with diagrams: mandatory if source is handed over (D15), recommended otherwise | 3 to 4 |
| Release 0.4.1 | Documentation release; tag | 1 |

### G4: Shadow period (software 3 to 4 days before it starts; the period itself is the factory's)

| Item | Content |
|---|---|
| **Shadow comparison** (new, small) | The human inspector's verdict for each board is recorded beside the machine's: an import of the factory's inspection log by board ID, or a two-button entry at the review station. A report per shift and per week: agreements, machine-only NG (false calls, after review), human-only NG (escapes), per defect type, with counts and bounds; exported with the usual CSV. New row REQ-TST-009 |
| **Threshold tuning loop** | Already exists (Compare's Try other thresholds, Save to Recipe with a reason, the recipe revision, the re-validation on the locked set). The procedure in the engineer manual says who may tune during shadow and that every tuning is followed by a validation run before it goes live |
| **Drift monitor** | Already exists (REQ-INSP-019). Its alarms are in the operator manual; its limits are set from the first two shadow weeks |
| Exit | The comparison report meets D13; the company and factory sign G4 |

### G5 and G6: Review-only, then unattended with audits (software 2 to 3 days)

| Item | Content |
|---|---|
| **Sampled audit mode** (new, small) | Every Nth OK board (D14) is flagged for a human look at the review station; the human's verdict is recorded beside the machine's; the shadow comparison report continues on the sampled boards. New row REQ-TST-010 |
| **Master samples each shift** | Already exists (REQ-INSP-017): inspection is blocked at shift start until the known-OK and known-NG boards are judged correctly |
| **Model change procedure** | Already enforced in software: a new version installs inactive, goes through the go-live gate against the locked set, and is activated with an audit entry; the procedure adds a re-validation report and the factory's sign-off before activation on the line |
| **Support contract** | In force from G6; the support bundle and runbook are its instruments |

### Between G1 and G3: production plan Stages 2 and 3 (the boxes; 28 to 36 days, tags `v0.4.1` and `v0.5.0`)

These are the handover boxes of section 2a and therefore precede G3. Stage 2: the test-suite restructure, lint extraction, 12-minute CI, screenshot approval from CI, `Makefile`, `tests/README.md`, `CONTRIBUTING.md`, `docs/MAP.md`, the architecture document restructured with diagrams, UI coverage measured. Stage 3: the service split, typed results and `docs/API.md`, the settings profile, one-step rollback with the upgrade rehearsal, the migration matrix with fixture databases, `docs/schemas/` for the line adapter's files; `InspectionCycle` and the accounts were already pulled into G1. Stage 4 (engine out of process) begins only when the company's camera project is scheduled; the typed API from Stage 3 is what makes it a two-to-three-week job then. If section 2b's first cut is taken, these stages precede the source handover instead of the binary one.

### G3 package: see the table above (12 to 16 days). Add to it: `docs/API.md`, `docs/schemas/`, `docs/operations/metrics.md`, and a box-by-box evidence sheet for section 2a that the company signs.

## 5. Register changes

Add the six rows of the production plan (REQ-SET-023 to -027, REQ-LOG-010) and these:

| New row | The app shall… | Acceptance (proposed) | Priority |
|---|---|---|---|
| REQ-INSP-020 | inspect boards that arrive in a watched input folder without an operator's action | A complete image file in the input folder is inspected within 2 s of arrival, moved to `done/` or `failed/`, and never inspected twice; a partial file is waited for; the file-naming contract is validated with a coded refusal | MUST G1 |
| REQ-INSP-021 | write a result per board to an output folder within 1 s of the verdict | JSON and one-line CSV with board ID, view, verdict, time, model version, recipe revision, defects; written atomically; the end-of-shift CSV lists every board | MUST G1 |
| REQ-TST-009 | record a human verdict beside the machine's for a board and report agreements, escapes and false calls per period and per defect type with counts and bounds | Import by board ID or entry at the review station; weekly report exported as CSV and PDF | MUST G1 |
| REQ-TST-010 | flag every Nth OK board for a human audit and fold the result into the comparison report | N set by an Admin per board model; the flag shows on the review station; the audit verdict is recorded with who and when | MUST G1 |

Move to MUST G1: REQ-USR-002 to -006, REQ-SET-010, REQ-SET-022, REQ-LOG-006, REQ-LOG-007, REQ-SET-011. Reword REQ-SET-006 into two rows: operator scope (G1) and full UI (G3 or Stage 3). Mark REQ-SET-013 done by REQ-TRN-021 or reword it.

## 6. What this plan refuses to do

- Hand over for any defect type whose G2 result did not meet the G0 target, or quote any number from drawn boards as accuracy.
- Skip the shadow period, or let a Trial model judge boards on the line.
- Ship a station without passwords, a licence, a signed build, a disk guard or a heartbeat.
- Change how a verdict is computed during Stages 1 to 3; the regression set stays byte-identical to `b5bf413`.
- Put a web front end, a database daemon or a metrics stack on the station.

## 7. Risks that software does not remove

| Risk | Mitigation in this plan |
|---|---|
| The factory delivers too few NG boards to pass G2 with a useful bound | D12 names the counts up front; the report says the bound honestly; scope narrows rather than the number being rounded |
| Photographs on the line differ from the photographs used for validation (lighting, position, a new camera) | G2 is run on images from the line's own imaging station, never from a bench; the drift monitor alarms; the master samples each shift catch a changed setup before boards do |
| An escape reaches a customer of the factory | The shadow and audit data show the measured escape rate; the contract (Legal & Compliance standard) names the targets and the limits of liability; every verdict carries its evidence, model version and recipe revision, so an escape can be traced to a decision |
| Jay is unavailable | The support runbook, the release kit, the signed binaries and source in escrow (D15); Stages 2 and 3 make the code ownable |
| The company tunes thresholds without re-validating | The procedure requires a validation run before a recipe revision goes live; the audit shows every change; the go-live gate refuses a worse model |

## 8. Exit checklist for every gate

- [ ] The gate's document signed by the named parties, with the evidence attached.
- [ ] All CI green on the tag; the nightly green the night before.
- [ ] `tests/regression/expected.json` identical to `b5bf413`.
- [ ] Register status updated; trace matrix green; release note and gate record honest.
- [ ] A reviewer agent that did not see the work has checked each exit criterion and reported it met or not, with evidence; every "not" answered in writing.
- [ ] The progress file's last line names the gate and the tag.
