# ADR 0007: The default Minimum defect area until the customer's size is agreed

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-08
- Decides: the product owner (Jay), until a tech lead joins
- Related: stage S30 of the Stage 1 plan; REQ-INSP-014, REQ-RCP-006, REQ-TRN-012; record
  `docs/tests/2026-10-08-public-dataset-check.md`

## Context

REQ-INSP-014 asks for 0 missed Critical defects at or above the minimum defect size agreed with the customer, on the
locked validation set. Neither the size nor the set exists yet. On DeepPCB, a public research dataset of scanned,
thresholded boards whose labelled defects its authors mostly drew in by hand (an internal check, close to synthetic,
not accuracy), the golden-board comparison with the default recipe missed 324 of 3,140 labelled defects, 242 of them
opens and mousebites. A smaller Minimum defect area found more boxes and left more regions on no labelled box:

| Minimum defect area | Missed boxes | Regions on no box |
|---|---|---|
| 40 px (default) | 324 | 786 |
| 20 px | 125 | 1,175 |
| 10 px | 71 | 1,550 |

No defect-free board went through the comparison, so a region on no box is not a false NG, and whether each is noise
or an unlabelled defect was not checked. Keeping regions by their longer side instead of their area did worse at
about the same number of regions on no box.

## Decision

1. **The default stays 40 px.** DeepPCB cannot set a default that judges a customer's boards: what a lower area does
   to misses and to false NG on camera photos is unknown (inferred: the scans differ from photos in noise, and most of
   their defects were drawn in by hand). The default holds until the customer's size is agreed (2 and 3).
2. **Each board model's minimum defect size is to be set from the size agreed with the customer** before its
   validation run, in mm at the board model's scale (REQ-RCP-006, S29), and the validation run on the locked set
   decides whether it meets REQ-INSP-014. The validation record states the size it ran with.
3. **The check runs again on customer photos** as soon as they are labelled (S31 to S35), with the same tool and
   counts, at the default and at the agreed size (`--min-area`).

## Alternatives

- Lower the default to 20 px or 10 px now: 125 or 71 missed boxes instead of 324 on DeepPCB, with 1,175 or 1,550
  regions on no box instead of 786, from data unlike the customer's.
- Judge a region by its longer side: did worse on DeepPCB (8 px or more: 195 missed, 1,166 regions on no box).

## Consequences

Until a board model's size is set, a defect whose difference region is under 40 px can be missed: on DeepPCB, 276 of the
324 missed boxes were found at a 1 px area. Nothing in the software enforces decision 2: REQ-RCP-006 (a SHOULD, not met
on main, partly met with S29) gives the size in mm, REQ-TRN-012's go-live gate (not met) covers AI model versions only,
and no requirement asks the software to refuse a validation run on the default size. Until one does, the person running
the validation checks the size and the validation record states it. No verdict changes now, and the synthetic regression
set is not touched.
