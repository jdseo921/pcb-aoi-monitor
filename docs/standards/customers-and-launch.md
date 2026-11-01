# AOI Standards – Customers & Launch

> **Copy of record.** Exported whole from [AOI Standards – Customers & Launch](https://claude.ai/code/artifact/af8143f9-f8c3-4f2f-bb40-9646d588c860) (Claude Docs, revision 11) on 2026-11-01. The source stays where Jay edits it; a change there is re-exported here in a pull request; if the two differ, the source wins until it is. What the export changed: [README](README.md#what-the-export-changed).

Oct 1, 2026 · @Jay Dongha Seo

**Mandatory.** Every implementation and code change made by Claude Code follows this standard, and other top-tier AI models review its responses and work. The review rules and the checklist for every change are in [AOI Standards – Charter](charter.md).

Every customer meets the product the same way: a demo that never fails, a validation on their own boards, a pilot with signed criteria, then a gated launch and close support.

## Demos

Any build tagged for a client runs its stage's demo offline from a cold start, with under 5 minutes of setup.

- **Rules (MUST).** Demo the release build only, never a developer setup. Lead with a failing board and open Compare; show settings only if asked. Show only finished features: unfinished pages hide behind a feature flag or show a "Coming in Stage N" card. Live training runs 2 minutes at most.
- **Their boards (SHOULD).** Use the customer's images whenever we have them, and end every demo with a report they keep.

Demo mode is a product feature, built and tested like any other, and it never touches production data.

| Feature | What it does | Needed by | In v0.1 |
| --- | --- | --- | --- |
| Demo workspace | One click loads a bundled board model, trained model, recipe and test boards | Stage 1 | Partly |
| Reset demo | Back to the start state in under 10 s | Stage 1 | No |
| Presenter theme | Light, high-contrast, larger text, Admin pages hidden | Stage 1 | No |
| Scripted run | Plays mixed OK and NG boards at a set pace, such as one every 3 s | Stage 1 | Partly |
| Demo report | One-click PDF with metrics, overlays and the model card | Stage 1 | Partly |
| Simulators | A camera feed from Stage 2; robot and MES from Stages 3–4 | Stage 2 on | No |

Each stage has a 5-, 15- and 45-minute script, and the 5-minute script must never fail.

| Stage | 5-minute script | What longer demos add |
| --- | --- | --- |
| 1 Image AI (now) | Run 10 mixed boards; one fails; Compare shows why; hand over the report | Train on their OK images for 2 minutes, validate on their NG samples, tune a threshold live, then recipes, model versions and data handling |
| 2 Live cameras | A live board, Top, Side and Bottom views, a verdict in under 1 s | Lighting changes, the 3D profile, calibration and soak results |
| 3 Robot cell | Load, inspect, unload sorted by verdict | Cycle time, the e-stop, recovery after a fault, safety interlocks |
| 4 MES / ERP | Scan a lot, inspect it, see the result in MES | Trace a lot back to its images, data mapping, IT review |

- **Before every demo (MUST).** Rehearse once on the demo laptop: release build installed and its version noted, demo workspace reset, Wi-Fi off, projector checked at 1920×1080 and 1366×768, presenter theme on, notifications off, only this customer's data visible, and a recording of the 5-minute script on the laptop and a USB stick.
- **When something breaks (MUST).** A crash: restart into the demo workspace in under 30 s. Slow training: switch to a pre-trained version. A camera or robot fails: switch to its simulator. A verdict looks wrong: open Compare and explain it. No projector: play the recording.

## Validation and accuracy claims

The strongest proof is the customer's own boards: we run a structured validation and hand back a report they sign, which passes gate G1.

1. **Agree on the data.** At least 70 OK images per board model (20 to train, 50 held out to test) plus every NG sample they have, labelled with types from the defect classification table, all from one camera and lighting set-up.
2. **Agree on targets before testing.** Proposed defaults: no missed Critical defect, a false call rate of 5% or less, and 1 s or less per image.
3. **Lock the test set.** Freeze the 50 held-out OK images and at least 30% of the NG samples, and never train on them.
4. **Train and test.** Run Training and the AI Model Test, then export the CSV, the overlays and a PDF report with the model card.
5. **Review together.** Walk through every miss and every false call in Compare and agree on fixes.
6. **Sign off.** The customer signs the validation report.

- **Their data (MUST).** Work under an NDA, keep their images only on encrypted machines, return or delete them at the end, and never show one customer's boards to another without written permission.
- **Claims carry counts (MUST).** Write "0 of 50 NG boards missed (95% upper bound about 6%)", never "99.9% accurate", "zero escapes" or synthetic results presented as real performance. Speak of the missed-defect rate and the false call rate: plain accuracy hides misses, since a model that passes every board scores 98% on a line with 2% NG.
- **Approved numbers only (MUST).** Every number in a slide, datasheet, website or proposal links to a validation report or test record signed by the AI lead, and every speed claim names the PC it was measured on. A customer's name, boards or numbers appear only with their written permission.

## Launch

Release 1.0 reaches the first customer in 1Q 2027 and Korea sales open in 2Q 2027, as the roadmap plans; each phase opens only when its gate's written criteria are met.

*The source shows this as a drawing; its text is transcribed here, see [README](README.md#what-the-export-changed).*

**Release 1.0 is two gates away; each phase opens only when its gate is passed.** Launch phases with dates from the roadmap; pilot dates and gate criteria are proposed.

| Phase | When | Who | Gate before the next phase |
| --- | --- | --- | --- |
| Alpha (we are here) | 4Q 2026 | in-house only | L1: real boards pass, installer works |
| Pilot | 4Q 2026–1Q 2027 | first customer | L2: validation signed, legal checklist done |
| **Release 1.0** | 1Q 2027 | 5–10 licenses | L3: 30 days stable, a reference customer |
| Korea launch | 2Q 2027 | Korea sales open | L4: localized UI, CE and CRA ready |
| Overseas | 2H 2027 | ASEAN, Japan, EU | |

L2 and L3 also need every row of the go/no-go checklist below marked Done.

- **Who decides (MUST).** The product owner passes each gate at a go/no-go meeting held one week before it, with every owner present. A row that is not Done is fixed, accepted in writing with a date, or the launch moves.
- **Dates move, criteria do not (MUST).** When a gate's criteria are not met, the date moves; criteria change only by a recorded decision.

Release 1.0 (L2) and Korea general availability (L3) each need every row below Done, with its evidence linked.

| Area | Must be true | Owner |
| --- | --- | --- |
| Product | Scope frozen and every MUST requirement done, shown by the trace matrix | Product owner |
| Engineering and security | The release gate in [AOI Standards – Engineering](engineering.md) passed, including the 8-hour soak; SBOM published; a penetration test done before general availability | Quality lead, tech lead |
| AI | A signed model card for each launch board model, and the validation report | AI lead |
| Legal | The checklist in [AOI Standards – Legal & Compliance](legal-and-compliance.md) ticked | Product owner |
| Documentation | Manual, installation guide and release notes published in English and Korean | Application engineer |
| Support | Support channel staffed, a P1 on-call person named, knowledge base started | Support lead |
| Sales and operations | Price list, datasheet, demo kit and product page approved; one test order run end to end, from license key to invoice and installer download | Product owner |
| Customer | Site acceptance test signed and operators certified | Application engineer |

## Pilots

A pilot proves value on one customer line in 4 to 8 weeks (proposed), against success criteria both sides signed before it started.

- **Signed first (MUST).** A pilot agreement from [AOI Standards – Legal & Compliance](legal-and-compliance.md) sets the board models, views, station, duration, success criteria and the price if they buy.
- **Success criteria (MUST).** Start from the validation targets above: no missed Critical defect, at most 5% false calls, at most 1 s per image.
- **Weekly rhythm (MUST).** A weekly check-in with the customer's quality engineer, followed by a one-page written summary.
- **Clear exit (MUST).** Success leads to the quote already agreed. A miss gets a written root cause and one decision: extend once, or stop.
- **Commitment (SHOULD).** A modest fee, credited against the purchase, keeps both sides committed. Run one pilot at a time until the first converts, and at conversion ask permission to publish a case study and name them as a reference.

## Pricing and editions

One codebase and one installer serve every customer: editions are license flags, prices are per station and per edition in one dated price list, and every discount follows a written rule.

| Edition (proposed) | Adds | Matches |
| --- | --- | --- |
| PoC / Demo | Image files only, a time-limited license, demo mode | Stage 1 |
| Standard | Live cameras, lighting control, 3D profile | Stage 2 |
| Automation | Robot cycle and safety interlocks | Stage 3 |
| Enterprise | MES / ERP, site server, MES login | Stage 4 |

- **Pricing model (open decision for Jay).** A perpetual license per station plus yearly maintenance, which factory software commonly uses, or a yearly subscription. Maintenance is often priced at around 15–25% of the license each year (inferred, not researched).
- **License keys (MUST).** Signed offline keys bound to the station's machine ID carry the edition, expiry and features, and work without internet. A customer moves up an edition with a new key, never a reinstall, and a locked feature shows a one-line note such as "Available in Automation", never a dead button (SHOULD).
- **Customer profiles (MUST).** Language, retention, default thresholds and report logo live in a versioned profile file per customer, never in code.
- **Price list (MUST).** One list in KRW, with USD and EUR for overseas, approved by the product owner; quotes stay valid for 30 days (proposed).
- **Separate lines (MUST).** Every quote lists software, hardware, installation, training, validation service and maintenance on their own lines, so services are never given away unseen. After the pilot, validation on customer images, recipe set-up and on-site training are billed services (SHOULD).
- **Discounts (MUST).** Volume and pilot-credit rules are written down; anything beyond them needs the product owner's approval.
- **One voice (MUST).** Only the product owner commits dates, features, prices or accuracy to a customer, and always in writing. A roadmap shared with customers shows dates beyond the next release as quarters, never days.

## Onboarding and acceptance

Every customer goes through the same six steps, and each step ends with a signature.

1. **Site survey.** PC, network, power, space and ambient light checked against the installation guide.
2. **Factory acceptance test (FAT).** Before shipping, the agreed test set of the customer's boards runs on our reference station and meets the targets.
3. **Installation and commissioning.** Install, activate the license, set up cameras and lighting (Stage 2 on), and create the golden boards and master samples.
4. **Site acceptance test (SAT).** On the installed station, the same test set meets the targets, an 8-hour run completes, and every role works.
5. **Training and certification.** Operators 2 hours, Engineers 1 day, Admins half a day (proposed); each ends in a short practical test and a certificate, refreshed yearly.
6. **Handover.** Manuals, a backup of recipes and models, support contacts and the escalation path, signed for by the customer.

- **Standard forms (MUST).** Survey, FAT, SAT and training records use the same templates, so every site is comparable.
- **Time to value (SHOULD).** From installation to a signed SAT in 10 working days or fewer (proposed).

## Platform support and lifecycle

Factory PCs stay in service for years, so stations run only on Windows editions Microsoft still patches, and every release of ours has a published end of support.

| Windows edition | Our support | Microsoft patches it until |
| --- | --- | --- |
| Windows 11 IoT Enterprise LTSC 2024 | Recommended for new stations | 10 October 2034 |
| Windows 11 Enterprise LTSC 2024 | Supported | 9 October 2029 |
| Windows 10 IoT Enterprise LTSC 2021 | Supported on existing PCs | 13 January 2032 |
| Windows 11 Pro or Enterprise, yearly versions | Supported on a version still being patched | 25H2: 12 October 2027 for Pro, 10 October 2028 for Enterprise |
| Windows 10 Home or Pro | Not supported | Ended 14 October 2025 |

- **Pro PCs update yearly (MUST).** Windows 11 Pro 24H2 stops getting patches on 13 October 2026, so every Pro station, demo laptops included, moves to 25H2 before then.
- **One published PC spec (MUST).** The datasheet and installation guide name the minimum PC: 64-bit Windows from the table, an NVIDIA GPU with CUDA where the station uses GPU acceleration (GUI §6), and an SSD of 1 TB or more, 2 TB recommended (proposed, from about 18 GB of raw images per shift at 3 views, 3,000 boards and 2 MB per image). Whether release 1.0 needs a GPU is still open in [AOI Standards – Charter](charter.md).
- **Support for our versions (MUST).** Each major version gets bug and security fixes until 24 months after the next major version ships (proposed). Customers get 12 months' written notice before a version, a Windows edition or a GPU generation loses support.
- **Runtime in the box (MUST).** The installer carries its own Python 3.11 and libraries, so customers never install Python. We move to a newer Python before 3.11 stops getting security fixes, around October 2027 (approximate).
- **End of support is not end of use (MUST).** An unsupported version keeps running, with its data and exports intact; it just gets no more fixes.

## Support and the first 90 days

Any station problem must be diagnosable from a support bundle without the customer's images leaving the site, and each new customer gets close attention until a written review at day 90.

| Priority | Means | Target (proposed) |
| --- | --- | --- |
| P1 | Line stopped, a missed defect, lost data, a crash or a frozen window | First response within 4 business hours; hotfix |
| P2 | Degraded, with a workaround | First response within 1 business day; fixed in the next release |
| P3 | Cosmetic or wording | Fixed in a coming release |

- **Diagnose without images (MUST).** The About dialog shows app, model, recipe and schema versions, the license and the station ID, with one Copy button for tickets. Remote sessions start only when the customer opens them and watches. An Admin health page shows disk, GPU, camera and database status and the last 24 hours of throughput and NG rate (SHOULD).
- **Field issues become tests (SHOULD).** Each missed defect or false call from the field becomes a regression case, using the customer's images only with their written permission.
- **Customer requests (MUST).** Each request is logged with the customer, the problem in their words and who asked. The product owner answers within 5 business days (proposed): accepted with a target release, declined with a reason, or parked with a review date.
- **First 90 days (MUST).** For the first 2 weeks after go-live, an engineer is reachable during all the customer's shifts and their numbers are checked daily. After that, weekly checks hold to 0 missed defects, a false call rate of 5% or less and at most 1 hour of downtime from our software per station per month, with a satisfaction survey at day 30 and day 90 aiming for 8 out of 10 or better (proposed). At day 90, Jay gets a written review: what worked, the top five issues, and the roadmap changes they lead to.

## Customer documents and materials

Every customer document has one owner and one event that forces its update, uses the glossary's words, and makes only the claims the validation rules above allow.

| Document | Owner | Updated when |
| --- | --- | --- |
| User manual, with Operator, Engineer and Admin chapters | Application engineer | A release changes a screen or step |
| Installation guide: PC, ports, antivirus, licensing | Tech lead | Requirements or ports change |
| Release notes | Product owner | Every release |
| Error code catalogue | Tech lead | A new error code is added |
| Model card and validation report | AI lead | Each model or validation |
| Security pack: two-page overview, SBOM, open-vulnerability summary, policies, questionnaire answers, and the penetration test letter once done | Tech lead | Every release; complete by general availability |
| Training slides and certificates | Application engineer | Each major release |
| Datasheet, product page, demo video and case study | Product owner | An edition, price or published result changes |

- **Tried by a reader (MUST).** Someone in the reader's role follows each changed step on the release build before it ships, and screenshots are regenerated from that build.
- **Both languages (MUST).** Korean and English versions ship together. Korean is written or reviewed by a native speaker who knows SMT terms; machine translation is only a first draft.
- **Approved and on time (MUST).** The product owner approves each sales asset before it is published. The validation report template is ready by L1, the datasheet and demo video by release 1.0, and the product page, case study and launch plan by Korea general availability.
- **Demo kit (SHOULD).** A one-page product sheet, a short video per stage, a screenshot pack, an IT one-pager (data stays local, the network is off by default, what MES needs), a roadmap slide with the stage gates and a FAQ, refreshed from the current build at each gate.

## Sources

The Windows dates above were checked against these pages on 1 October 2026; launch dates and the GPU requirement come from the roadmap and the GUI specification.

- [Windows 11 release information](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information), Microsoft
- [Windows 10 release information](https://learn.microsoft.com/en-us/windows/release-health/release-information), Microsoft
