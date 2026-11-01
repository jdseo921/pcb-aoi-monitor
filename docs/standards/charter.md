# AOI Standards – Charter

> **Copy.** Exported whole from [AOI Standards – Charter](https://claude.ai/code/artifact/cdb76b42-fd68-42e9-8c59-25abdf86b114) (Claude Docs, revision 24) on 2026-11-01. The source stays where Jay edits it; a change there is re-exported here in a pull request; if the two differ, the source wins until it is. What the export changed: [README](README.md#what-the-export-changed).

Oct 1, 2026 · @Jay Dongha Seo

## Mandatory for Claude Code and AI review

Every implementation and code change Claude Code makes in this project follows these standards, and other top-tier AI models review Claude's responses and work against them. Work that would not survive that review is not done.

1. **Read first.** Before changing anything, Claude reads this Charter and the standard that covers the work, and works through the checklist for every change below.
2. **No silent exceptions.** A MUST is never skipped. When a request conflicts with a MUST, Claude says so and goes ahead only with Jay's explicit approval, recorded in the change note.
3. **Show the evidence.** Every claim that something is done names what was checked: the test run and its output, the file and line, or the screen. "Should work" is not evidence.
4. **Write for the reviewer.** Change notes name the rules applied, the assumptions made and anything left undone, so an outside reviewer can verify the work without asking.
5. **Close every finding.** Each review finding is fixed, or answered in writing with the reason it stands; none is ignored.
6. **A person approves.** Claude never approves or merges its own change; Jay signs off until a second engineer joins.

## How to use this set

These four docs are the bar every change to the AOI app, and every step toward selling it, is measured against, from the Stage 1 PoC to the 1Q 2027 release and beyond.

- **MUST** blocks a merge or a release. **SHOULD** is the default; skipping it needs one written line of reason in the change note. **MAY** is optional.
- Every rule names something checkable: a number, a test, a file or a screen. Numbers marked GUI § come from the GUI specification; numbers marked proposed are our own starting points until a customer or a test confirms them.
- Jay owns the set. Anyone, Claude included, proposes changes as comments; accepted changes are edited in place, and the set is reviewed at every stage gate and at least once a quarter.
- The technical reference for the current build is `docs/ARCHITECTURE.md` in the shared `pcb-aoi-app` folder.

## Five principles

When two goals conflict, the principle higher on this list wins.

1. **Operator first.** The verdict is readable within 3 seconds from 2 m away; everything else is one click deeper.
2. **Every verdict explains itself.** No OK or NG is shown, stored or exported without its evidence: region, metric, threshold, model version and recipe revision.
3. **Demo-ready on every merge.** The main build always runs the current stage's demo script end to end, offline.
4. **Measure, don't guess.** Speed, accuracy and false calls are measured by tests and reports, never estimated in a meeting.
5. **One pipeline, many stages.** Image files, cameras, the robot and MES all feed the same inspection engine; each stage adds an adapter, never a rewrite.

## The standards

Three standards sit under this Charter. Read the one that matches the work before you start it.

| Standard | Sets the standard for | Read it before |
| --- | --- | --- |
| [AOI Standards – Engineering](engineering.md) | Architecture, screens, data, AI models and data, performance, security, testing and release, workflow | Changing any code, data or model |
| [AOI Standards – Customers & Launch](customers-and-launch.md) | Demos, validation and accuracy claims, launch, pilots, pricing, onboarding, platform support, support, customer documents | Any customer meeting, quote, pilot or launch |
| [AOI Standards – Legal & Compliance](legal-and-compliance.md) | Contracts, ownership, privacy, licenses, IP, regulations and certifications | Signing anything, adding a dependency or entering a market |

## Checklist for every change

Claude Code works through this list for every change and states the result in the change note; a box that does not apply is marked n/a with a reason.

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

## Who decides

Every decision that changes what a customer receives has one named owner. While the team is small one person holds several roles, but the role names stay fixed as it grows.

| Role | Owns | Has the final say on |
| --- | --- | --- |
| Product owner (Jay today) | Roadmap, requirements, pricing, customer commitments | What ships and when; anything promised to a customer |
| Tech lead | Architecture, code quality, design records | The technical approach and the service API |
| AI lead | Datasets, labeling, models, validation reports | Whether a model passes the go-live gate |
| Quality lead | Test plans, release gates, the reference PC | Go or no-go for each release |
| Support lead | Field issues, support bundles, the knowledge base | The P1, P2 or P3 priority of a field issue |
| Application engineer | Demos, pilots, installs, customer training | What a given customer sees, and when |

Decisions that bind the product go in the decision table below or in a design record, with a date and an owner.

## Stage gates

No stage starts until the previous gate passes.

*The source shows this as a drawing; its text is transcribed here, see [README](README.md#what-the-export-changed).*

**Each stage must pass its gate before the next one starts.** Stages and dates from the roadmap plan; gate criteria set by these standards.

| Stage | Second line | Third line | Gate before the next stage |
| --- | --- | --- | --- |
| **Stage 1: Image AI** (current) | 8 weeks (plan) | Now: v0.1 | G1: Customer signs validation report |
| Stage 2: Live cameras | 8 weeks (plan) | 2D/3D, lighting | G2: 8-hour live run under 1 s per board |
| Release 1.0: 1st customer | 1Q 2027 | 5–10 licenses | G3: Installer + license, Korean UI + manual |
| Stage 3: Robot cell | 2027 (plan) | 12–16 weeks | G4: Load, inspect, unload + e-stop |
| Stage 4: MES / ERP | 2027 (plan) | 12–16 weeks | G5: Every lot traced station to MES |

A gate passes only when its criteria are shown in a demo build, not just claimed.

Stage 1 is current, so G1 is next: a customer signs a validation report run on their own boards (steps in [AOI Standards – Customers & Launch](customers-and-launch.md)).

## Decisions

Four foundations are decided; nine questions still need Jay.

| Area | Decision | Why |
| --- | --- | --- |
| Desktop stack | Python 3 with PySide6 (Qt 6) | Allowed by the GUI spec; its LGPL license suits selling many seats |
| AI framework | PyTorch, `.pt` model files | Named in the GUI spec; uses CUDA when present, CPU otherwise |
| Storage | SQLite plus one workspace folder per station | Local-first and easy to back up; the path to PostgreSQL stays open |
| AI approach | Learn from good boards first; NG samples calibrate the threshold | Customers have few defect samples at PoC start |

Open product questions:

- [ ] Re-baseline the schedule? The plan put Stages 1 and 2 in Q2–Q3 2026. v0.1 exists on 1 Oct 2026, so the 16 planned weeks would end around late January 2027 (inferred).
- [ ] GPU or CPU-only stations for release 1.0.
- [ ] Default acceptance targets per customer (proposal in [AOI Standards – Customers & Launch](customers-and-launch.md)).
- [ ] Korean UI at release 1.0 (proposed) or with the 2H 2027 localization work.
- [ ] Move the code into a GitHub repository; today it lives only in the project folder.

Open business questions:

- [ ] Pricing model: a perpetual license per station plus yearly maintenance, or a yearly subscription ([AOI Standards – Customers & Launch](customers-and-launch.md)).
- [ ] Models trained for a customer: licensed to them (proposed default) or owned by large customers ([AOI Standards – Legal & Compliance](legal-and-compliance.md)).
- [ ] Product name, cleared and filed as a trademark in Korea before launch ([AOI Standards – Legal & Compliance](legal-and-compliance.md)).
- [ ] Patents: file on any method worth protecting before the first public demo, or decide not to ([AOI Standards – Legal & Compliance](legal-and-compliance.md)).

## Words we use

Write for an operator on a noisy line: short, specific, in their words, and always saying what to do next.

- **Plain words (MUST).** Buttons name the action, such as Save Recipe or Next Board. Messages say what happened and what to do, with the error code: "Camera not found (AOI-CAM-003). Check the cable, then press Retry." Operator screens use no engineering jargon ("AI score", not "anomaly z-score"), and nothing says "fatal", "illegal" or "invalid user".
- **Numbers (MUST).** The value, a space, then the unit, with ISO dates and 24-hour time: 0.8 s, 12 px, 2026-10-01 14:05.
- **Korean style (MUST).** Formal polite endings (합니다체) in manuals and messages, short noun phrases on buttons (검사 시작, 레시피 저장), and the factory's own abbreviations kept as they are: OK, NG, ROI, AOI.
- **One word per concept (MUST).** Only the terms below, in the app, reports, manuals and sales material alike; a new term is added here first. The Korean terms are proposed and get confirmed with the first customer's quality team.

| Term | Korean | Meaning | Not |
| --- | --- | --- | --- |
| Board model | 기종 | One PCB design and revision, such as TBOX-A1 rev 3 | product type, part number |
| Board revision | 보드 리비전 | The revision printed on the board, such as R1, kept with the images taken of it | board version |
| View: Top, Bottom, Side | 뷰: 윗면, 아랫면, 측면 | The side of the board a camera sees; each AI model judges one view | angle, face |
| AI model | AI 모델 | A trained model version for one board model and view | "model" on its own |
| Trial | 시험용 (Trial) | An AI model, or the images it learned from, that has not passed the Validated checks, as when one person labelled them; it judges boards only while no Validated AI model has gone live, and every screen, record and report names it Trial | pilot, beta |
| Validated | 검증 완료 (Validated) | An AI model, or the images it learned from, that passed the Validated checks, a second person's label check among them; once one has gone live, a Trial one never replaces it | approved, certified |
| Golden board | 골든 보드 | The learned reference image of a good board | master image |
| Master sample | 마스터 샘플 | A physical known-OK or known-NG board for shift-start checks | golden board |
| Shift check | 교대 점검 | Judging the master samples at the start of a shift; boards are inspected only after one judges every sample right | start-up check |
| Regression set | 회귀 시험 세트 | Images with expected verdicts that every release must reproduce; engineers also say golden-image set | test images |
| Recipe | 레시피 | ROIs, thresholds and settings for one board model | program, job |
| ROI | 검사 영역 (ROI) | A region with its own check type and threshold | zone, window |
| Verdict: OK, NG, WARN | 양품, 불량, 확인 필요 | Pass, fail, or needs a person to look | pass, fail, warning |
| Defect | 결함 | One fault of one type from the classification table, at one place | error |
| Severity: Critical, Major, Minor | 치명결함, 중결함, 경결함 | The severity classes of the classification table | priority |
| False call | 과검출 | A good board or area marked NG | false alarm, overkill |
| Missed defect | 미검출 | A defective board marked OK | escape, false OK |
| Threshold | 임계값 | The value where a check turns from OK to WARN or NG | limit, cut-off |
| Training | 학습 | Building a new AI model version from samples | learning |
| Validation | 검증 | Testing an AI model on a locked set it never saw | test run |
| Station | 검사 스테이션 | One PC with its cameras, running the app | machine, cell |
| Workspace | 작업 폴더 | The folder that holds a station's data | project |
| Customer | 고객 | The company whose boards these are; its images are kept encrypted on the station, apart from every other customer's | client |
| Recovery key | 복구 키 | The key shown once when a customer's images are first kept, which opens them on another PC if the station's own key is lost | backup key |
