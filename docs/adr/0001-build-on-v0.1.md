# ADR 0001: Build release 1.0 on v0.1

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-01
- Decides: the product owner (Jay), until a tech lead joins
- Related: #9, the known-gap issues #1 to #6 and #11, [Stage 1 requirements](../requirements/stage1.md),
  [resolution test](../tests/2026-10-01-resolution-test.md)

## Context

v0.1 was delivered on 2026-10-01: 3,454 lines of Python, with 1,890 in the screens and 1,361 in the engine, data
layer and hardware interfaces. It has all nine pages of [ARCHITECTURE.md](../ARCHITECTURE.md) §5, self-training
from good boards, the Compare page, recipes, the AI Model Test and log export. Its modules follow the layers the
Engineering standard asks for (screens, then `AppContext`, then the engine, then data and hardware), and the
engine and data layer import no Qt. The screens do not keep to those layers, though: pages run SQL, write through
`ctx.db`, build their own `Inspector`, and inspect or import images on the UI thread (#11).

It has been tested only on synthetic boards. Checked against the Engineering standard, it has the six known gaps
the standard lists: weights-only model loading (#1), the data layer (#2), screens (#3), logs and errors (#4),
tooling (#5) and live batch results (#6). The review of this record found a seventh, the layering above (#11). Of
the 91 Stage 1 requirements, 9 are met already and 44 in part.

The GUI spec (§6) also allows .NET and C#, so a rewrite was a real option.

## Decision

Release 1.0 grows out of v0.1. We keep:

- the stack: Python, PySide6, PyTorch and SQLite as the Charter decided, Python 3.11 as the Engineering standard
  pins it, and OpenCV as v0.1 uses it;
- the layers: screens, then `AppContext`, then the engine, then the data and hardware adapters;
- the pages and navigation of ARCHITECTURE.md §5;
- the inspection pipeline's shape (align, compare with the golden board, AI model, ROI checks, verdict) and its
  results as data (`InspectionResult`, `Check`, `Defect`).

We fix the known gaps first, before new features: the standard's six in its order, with #11 alongside #3, since
both change the pages. #1 is a security fix, and #2 must land before any requirement with a schema impact. #5 is
under way in pull requests #7 and #8.

v0.1 workspaces hold test data only and are not upgraded. The first numbered migration (#2) creates the schema
from scratch, so customer data only ever lives in the migrated schema.

How the AI path changes for real camera images is left to the feasibility test on real boards (#10). Any change
to the model architecture gets its own design record.

## Alternatives considered

- **Rewrite in C# and .NET.** It gives a native Windows UI, but training would need TorchSharp or a second
  Python process, and the work would restart from nothing. Rejected.
- **Rewrite in Python on a new design.** v0.1's modules already follow the standard's layers, and its layering
  breaks sit in the pages, where #11 fixes them; a rewrite fixes none of the gaps by itself. Rejected.

## Consequences

- Stage 1 starts from working screens. Lint, strict type checks, tests on Windows and Linux, and security scans
  arrive in CI with #7 and #8, which are still open.
- Once #11 moves the pages' database and engine calls behind `AppContext`, the AI method can change without
  touching a page.
- We carry v0.1's debt: the known gaps come before features. #2 blocks the 27 requirements marked Sch.
- The resolution test of 2026-10-01 timed v0.1 on synthetic boards, on a cloud VM with 4 virtual CPUs and no GPU.
  Inspection took a median 7.0 s at 5 MP (95th percentile 7.2 s), 97 % of it in the compare step. A rewrite of
  that step with the same results measured 0.34 s; put in place of v0.1's compare step, that gives an estimated
  0.52 s per board (95th percentile 0.55 s), plus 0.12 s to decode a PNG file. So the pipeline keeps its shape,
  and the rewrite is #12. At 12 MP the same estimate is 1.26 s (1.42 s), over the budget, so a higher
  resolution needs more than that rewrite.
- Revisit this record if the feasibility test on real boards misses the validation targets with this pipeline
  shape.
