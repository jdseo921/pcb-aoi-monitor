# AOI Standards – Legal & Compliance

> **Copy.** Exported whole from [AOI Standards – Legal & Compliance](https://claude.ai/code/artifact/e99c8a5f-ee90-4fdf-a308-745d4c4edd87) (Claude Docs, revision 11) on 2026-11-01. The source stays where Jay edits it; a change there is re-exported here in a pull request; if the two differ, the source wins until it is. What the export changed: [README](README.md#what-the-export-changed).

Oct 1, 2026 · @Jay Dongha Seo

**Mandatory.** Every implementation and code change made by Claude Code follows this standard, and other top-tier AI models review its responses and work. The review rules and the checklist for every change are in [AOI Standards – Charter](charter.md).

This is a checklist, not legal advice: a lawyer reviews every contract, license text and policy before it reaches a customer.

## Ground rules

Four rules keep every deal consistent and every promise in writing.

- **Counsel review (MUST).** No contract, license text or policy reaches a customer until a lawyer has reviewed it.
- **One contract set (MUST).** Every deal starts from the standard templates; any change is a named deviation approved by the product owner.
- **No side promises (MUST).** Nothing said in a demo, email or chat binds the company unless it is in the signed contract, and staff say so when asked for commitments.
- **One filing place (MUST).** Signed contracts, NDAs and consents live in one place, with renewal and expiry dates tracked.

## Contracts

Five templates cover every deal, from the first shared image to a renewed maintenance year.

| Contract | When | Terms we hold to |
| --- | --- | --- |
| Mutual NDA | Before any images or plans are shared | Images used only for the stated evaluation, then returned or deleted |
| Pilot agreement | Before a pilot starts | Scope, success criteria, duration, who owns pilot results, price if they buy |
| EULA | Accepted at every installation | Per-station license, no transfer without consent, audit right, and the reverse-engineering carve-out the LGPL requires |
| Maintenance and support | At purchase, renewed yearly | Updates, the response targets in [AOI Standards – Customers & Launch](customers-and-launch.md), annual fee |
| Data processing agreement | Whenever our staff handle personal data | Purpose, security measures, deletion at the end |

- **An inspection aid, not a guarantee (MUST).** Contracts state that the system supports the customer's quality process and that release decisions stay theirs. We warrant that the software performs as documented and validated, never that no defect escapes.
- **Liability cap (MUST).** Total liability is capped, typically at the fees paid in the previous 12 months, and excludes indirect losses such as recalls or lost production where the law allows (proposed; counsel to confirm).
- **Objective acceptance (SHOULD).** Acceptance is tied to the signed validation report or the site acceptance test in [AOI Standards – Customers & Launch](customers-and-launch.md).
- **Governing law (SHOULD).** Korean law for Korean customers; arbitration, such as at the Korean Commercial Arbitration Board, for overseas deals.

## Ownership of customer images, results and models

The customer owns their images and results, we own the software and methods, and a model trained on their images is licensed to them for as long as their license runs (proposed default).

| Item | Owner | Our use |
| --- | --- | --- |
| Customer images and labels | Customer | Only for their project; deleted at the end |
| Inspection results and reports | Customer | Anonymous statistics only, and only if they agree |
| Models and recipes trained for the customer | Licensed to the customer while their license runs | A support copy only; never reused for others without written consent |
| Software, base models, training methods, improvements | Us | Unrestricted |
| Feedback and feature ideas | Us | Free to use, with no obligation |

- **Open decision for Jay.** License customer-specific models (the default above), or let large customers own them outright. Licensing keeps our methods ours and avoids disputes when a customer leaves; ownership is a concession for large accounts.
- **Deletion (MUST).** At the end of an engagement, or on request, the customer's images, labels and derived models are deleted from our machines within 30 days (proposed), and we confirm it in writing. What runs on their own stations stays theirs.

## Privacy

The product holds little personal data, only the names and IDs of the people who use it, and keeps it that way.

| Personal data | Why we hold it | Kept for |
| --- | --- | --- |
| User accounts: name, role, password hash | Access control and audit | Until the account is removed |
| Operator ID on results and audit entries | Traceability the customer requires | The customer's retention period |
| Support bundles, which may contain user names | Diagnosing a problem | 90 days after the ticket closes (proposed) |
| Telemetry, off by default | Product improvement | 13 months, anonymous (proposed) |

- **Nothing more (MUST).** No other personal data is collected, and capture set-ups keep hands and faces out of the images.
- **We process for the customer (MUST).** Data on a station belongs to the customer. When our staff touch it during support or validation, we work under a written processing contract, as Korea's PIPA requires for entrusted processing (Article 26) and the GDPR requires of processors (Article 28), and we never subcontract that work without the customer's consent.
- **People's requests (SHOULD).** Admins can export one person's records and remove their account; old results then keep only a pseudonymous operator ID.
- **Market check (MUST before each new country).** Confirm the local privacy law before the first sale there, such as Japan's APPI or the PDPA in Singapore and Thailand.

## Open-source and third-party licenses

We ship only code, fonts, models and data whose license we have checked, and we meet every duty those licenses carry.

| License type | In the shipped product | Our duties |
| --- | --- | --- |
| Permissive: MIT, BSD, Apache 2.0 | Allowed | Keep copyright notices and license texts, plus Apache NOTICE files |
| LGPL: Qt for Python (PySide6) | Allowed, as separate libraries only | Keep Qt as separate libraries users can replace; ship the license texts with a prominent notice; supply, or offer in writing, the full source of the Qt and PySide6 libraries we ship, changed or not; the EULA permits the reverse engineering this needs |
| SIL Open Font License: Noto Sans KR | Allowed | Ship the license; never sell the font on its own |
| GPL, AGPL | Not allowed | — |
| Non-commercial or research-only weights and datasets | Not allowed | — |
| No license stated | Not allowed | Treat as all rights reserved |

- **Inventory in CI (MUST).** CI builds the third-party list from the SBOM and fails on a forbidden or unknown license.
- **Notices shipped (MUST).** The About dialog and `THIRD_PARTY_NOTICES.txt` carry every required notice; today the main ones are PySide6 (LGPLv3), PyTorch (BSD-3-Clause) and OpenCV 4.5 or later (Apache 2.0).
- **Packaging (MUST).** Build with PyInstaller's one-folder mode, so the Qt libraries stay separate files a user can replace, and use only Qt modules offered under the LGPL: some add-ons, such as Qt Charts, are GPLv3 or commercial only. v0.1 uses none of them.
- **Weights and datasets (MUST).** Pretrained weights and public datasets carry their own licenses, often non-commercial; check them like code before use.

## Protecting our IP

The code, the models and the product name are the company's main assets, and each needs protecting before the first public demo.

- **IP assignment (MUST).** Every employee, contractor and intern signs an agreement assigning their work to the company before they write code; nobody contributes without one.
- **Trademark (MUST before launch).** Pick the product name, run a clearance search, and file in Korea (KIPO) first, then in the launch markets through the Madrid Protocol. Use ™ until registration and ® only after.
- **Patents (MUST decide before public demos).** If a method is worth patenting, such as the shift-tolerant golden-board comparison, file before showing it in public. Korea and the US allow 12 months' grace after your own disclosure (in Korea only when claimed with proof), but the European Patent Convention has no general grace period, so one public demo can block a European patent.
- **Trade secrets (SHOULD).** Ship the engine compiled, for example with Cython or Nuitka, because plain Python bytecode is easy to decompile, and keep training recipes and base-model data off customer machines where the edition allows.
- **Source code escrow (SHOULD offer).** Keep a standard escrow agreement ready for Enterprise customers who want to be able to maintain the software if we cannot.
- **Notices (SHOULD).** "© \[year\] \[company\]" in the About dialog, installer, manuals and source file headers.

## Regulations and certifications

Release 1.0 in Korea mostly needs privacy terms and sound contracts; each later market or stage adds duties, so each row is checked before the point it names. This is our reading of the rules, for counsel to confirm.

| Market or stage | Rule | What it asks of us | Check before |
| --- | --- | --- | --- |
| Korea, all stages | Personal Information Protection Act (PIPA) | A written processing contract whenever our staff handle customer data (Article 26), and no subcontracting without the customer's consent | The first pilot |
| Korea, all stages | AI Basic Act, in force since 22 January 2026 | Its main duties fall on "high-impact" AI in listed areas such as energy, health care, hiring, credit and transport; PCB inspection is not one of them | Release 1.0 |
| Korea, Stage 2 on | KC mark, under the Radio Waves Act and the Electrical Appliances and Consumer Products Safety Control Act | Any PC, camera or lighting we supply carries the KC mark; the software alone needs none | Choosing Stage 2 hardware |
| EU | Cyber Resilience Act | Vulnerability and incident reporting from our first EU sale; security requirements, conformity assessment and the CE mark from 11 December 2027 | The first EU sale, planned 2H 2027 |
| EU | AI Act | PCB visual inspection is normally not high-risk; high-risk duties now start on 2 December 2027 for listed uses and 2 August 2028 for AI inside regulated products | The first EU sale |
| EU | GDPR | A processor contract (Article 28) for EU customers' operator data | The first EU sale |
| EU, Stage 3 | Machinery Regulation (EU) 2023/1230, applying from 20 January 2027 | A robot cell we supply needs a risk assessment, a declaration of conformity and the CE mark | The first EU robot cell |
| All markets, Stage 3 | ISO 10218-1 and ISO 10218-2, 2025 editions | Safety design and validation of the robot and the robot cell | Stage 3 design starts |
| Japan, Singapore, Thailand | APPI; PDPA 2012; PDPA 2019 | Local privacy terms and rules for sending data abroad | The first sale in each country |
| Any export | Korea's strategic items control | Classify the software and any hardware we ship through the government's YesTrade service, and file the result | The first overseas sale |

- **EU reporting (MUST from the first EU sale).** Under the Cyber Resilience Act, an actively exploited vulnerability needs an early warning to the authorities within 24 hours, a notification within 72 hours and a final report within 14 days of a fix being available; a severe incident needs the same first two and a final report within one month. Reporting has applied since 11 September 2026, even to products sold before the Act's other rules start on 11 December 2027.
- **AI stays out of safety functions (MUST).** At Stage 3, guards, stops and interlocks run on certified safety hardware, never on our AI. AI that performs a safety function becomes a safety component and can make the system high-risk under the AI Act (our reading).
- **Customer change control (MUST).** Automotive Tier-1 suppliers usually work under IATF 16949 and must control changes to their inspection process, so the customer notice for verdict-affecting changes in [AOI Standards – Engineering](engineering.md) is part of what they buy.

Certifications follow customer demand (SHOULD):

| Standard | Covers | When |
| --- | --- | --- |
| IEC 62443-4-1 | Secure product development process | Align the process by release 1.0; certify when a customer requires it |
| IEC 62443-4-2 | Security features of an industrial component | Before Stage 4, when stations join plant networks |
| TISAX | Information security at automotive suppliers | Assess before the 2Q 2027 Korea campaign if Tier-1 customers ask |
| ISO/IEC 27001 | Company-wide security management | Once we hold several customers' data |

- **One owner (MUST).** The product owner keeps both tables current and reviews them with counsel before each new market or stage.

## Before the first paid customer

The first invoice goes out only when every box is ticked; most items take weeks, so they start now.

- [ ] NDA, pilot, EULA, maintenance and data processing templates reviewed by counsel
- [ ] EULA shown and accepted in the installer, with the LGPL carve-out
- [ ] Third-party notices complete and the CI license report clean
- [ ] Product name cleared and the trademark filed in Korea
- [ ] Patent decision recorded before the first public demo
- [ ] IP assignments signed by everyone who has written code, contractors included
- [ ] Privacy notice and processing contract ready
- [ ] Product liability and professional indemnity insurance quoted and bound
- [ ] Export classification recorded before the first overseas sale

## Sources

The outside facts in this standard were checked against these pages on 1 October 2026; counsel confirms them before we rely on them.

- [Open-source LGPL obligations](https://www.qt.io/licensing/open-source-lgpl-obligations), The Qt Company
- [OpenCV license](https://opencv.org/license/), OpenCV; [PyTorch license](https://github.com/pytorch/pytorch/blob/main/LICENSE), PyTorch
- [Grace period provisions in national laws](https://www.wipo.int/scp/en/national_laws/grace_period.pdf), WIPO
- [Personal Information Protection Act, English text](https://www.law.go.kr/LSW/eng/engLsInfoR.do?lsiSeq=270351), Korea Ministry of Government Legislation
- [Korea's AI Basic Act](https://www.kimchang.com/en/insights/detail.kc?sch_section=4&idx=33805), Kim & Chang
- [Conformity assessment and the KC mark](https://www.rra.go.kr/en/cas/intro.do), National Radio Research Agency
- [CRA reporting obligations](https://digital-strategy.ec.europa.eu/en/policies/cra-reporting), European Commission
- [AI Act and the AI Omnibus](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai), European Commission
- [GDPR, Regulation (EU) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj), EUR-Lex
- [Machinery Regulation](https://single-market-economy.ec.europa.eu/sectors/mechanical-engineering/machinery_en), European Commission
- [ISO 10218-1:2025](https://www.iso.org/standard/73933.html) and [ISO 10218-2:2025](https://www.iso.org/standard/73934.html), ISO
- [IEC 62443-4-1:2018](https://webstore.iec.ch/en/publication/33615) and [IEC 62443-4-2:2019](https://webstore.iec.ch/en/publication/34421), IEC Webstore
- [Information security and TISAX](https://www.vda.de/en/topics/digitization/data/information-security), VDA
- [APPI](https://www.ppc.go.jp/en/legal/), Japan PPC; [PDPA](https://www.pdpc.gov.sg/), Singapore PDPC; [PDPA](https://www.mdes.go.th/), Thailand MDES
- [YesTrade strategic items service](https://www.yestrade.go.kr/), Government of Korea
