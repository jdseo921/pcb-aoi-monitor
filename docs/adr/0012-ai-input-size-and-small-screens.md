# ADR 0012: The AI model's input size, and screens smaller than 1920 × 1080

- Status: Proposed under Jay's instruction of 2026-10-11 ("Make decisions that are the best for industry norm
  standards"). Jay's merge of this record accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-007, REQ-INSP-014, REQ-SET-004, #104; report
  `reports/2026-10-10-recalibration-and-deeppcb-training.md` in the project files (second pass); ADR 0008

## Context

**Input size.** The AI model scales each aligned board image to a square of `image_size` pixels before it learns or
scores it (256 by default, a multiple of the network's step of 16). The size is chosen per run on Training, with the
default from Settings, and is saved in the AI model's metadata and its model card, so each board model's active AI
model already carries its own. Training and Settings offered 128, 256, 384 and 512.

On DeepPCB, a public research dataset of thresholded scans close to synthetic (an internal check, never accuracy), the
AI model alone was trained on 7 groups of 20 defect-free templates, 60 epochs, on a cloud VM with 2 threads:

| Size | Defective called OK | Defect-free called NG | Warning (defect-free, defective) | Training | Scoring | Memory |
|---|---|---|---|---|---|---|
| 256 px | 115 of 168 | 1 of 168 | 9, 31 | 170 s a group (median) | 19.9 ms a board | 1,007 MB peak |
| 640 px | 34 of 168 | 6 of 168 | 22, 29 | 1,522 s a group | 86.9 ms a board | 2,047 MB peak |

At 640 px, the scans' own size, a 24 to 38 px defect keeps its size instead of shrinking to 10 to 15 px. 31 of the 34
misses are in one group whose templates include byte-identical copies.

**Screens.** REQ-SET-004 checks every page's screenshot at 1920 × 1080 and reviews the pages at 1366 × 768 and at 4K.
Since #104 the page area scrolls when the window is smaller than a page, and a field that takes keyboard focus is
scrolled whole into view. #378 measures Compare's Try other thresholds panel at 1920 × 1080; whether 1600 px wide
screens needed the panel to fit without scrolling was open.

## Decision

1. **The input size stays 256 px by default, and each training run may take 640 px.** 256 px is the usual input size
   for this kind of reconstruction or feature-based anomaly model (it is the default of the common open-source
   anomaly-detection libraries and of the MVTec AD benchmark's usual setup; inferred from their published defaults, not
   re-checked for this record), and it is the size measured against REQ-TRN-007's budget of 50 OK images in 10 minutes
   on a CPU. 640 px, the usual input size of general object detectors and the scans' own size above, is added to the
   choices on Training and Settings for board models with small defects. The size stays a property of each run, kept
   in its AI model's metadata, which is how inspection systems commonly hold resolution: in each board model's program
   rather than as one setting for the station. No new per-board-model setting is added; the engineer picks the size
   when training that board model's version, and the model card records it.
2. **1920 × 1080 stays the reference screen, and a smaller screen scrolls with nothing hidden.** It is the most common
   resolution of industrial panel PCs and line monitors, and REQ-SET-004 already checks screenshots at it. On a
   smaller screen the page area scrolls, and Tab brings each field whole into view, as WCAG 2.2 success criterion
   2.4.11 (Focus Not Obscured) asks. At 1600 × 900 every field of Compare's Try other thresholds panel is in view as
   laid out; at 1366 × 768 Tab reaches each one whole (`tests/test_compare_reevaluate.py`, the REQ-SET-004 test of
   each Try panel field below the reference screen).
   No page is laid out again for 1600 px.

## Alternatives

- Make 640 px the default: 81 fewer defective boards called OK on DeepPCB, but 5 more defect-free boards called NG,
  13 more Warnings, about 9 times the training time (beyond REQ-TRN-007's CPU budget on this VM) and 4 times the scoring
  time, from data unlike the customer's.
- A separate input-size setting on each board model: the size already travels with each board model's AI model, and a
  second place to set it could disagree with the model in use.
- Lay every page out to fit 1366 × 768 without scrolling: the 1920 × 1080 layouts would lose the room the standard's
  48 px targets and 14 pt text need, for a screen no customer station has been named with.

## Consequences

An engineer who trains at 640 px waits longer: on a CPU the run can exceed REQ-TRN-007's 10 minutes (25 minutes for
20 images on the VM above), so 640 px suits a station with a CUDA graphics card, and Training shows the time left as the
run goes. Memory at 640 px for 50 images at the customer's resolution is not measured; the training memory record
(`docs/tests/2026-10-09-training-memory.md`) is at 256 px. Which size a board model needs is decided by its validation
run on the locked set at the agreed minimum defect size (ADR 0008), not by DeepPCB. No verdict changes now: the default
is unchanged, an AI model trained before keeps its own size, and the synthetic regression set is not touched.
