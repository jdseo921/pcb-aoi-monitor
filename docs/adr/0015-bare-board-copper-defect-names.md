# ADR 0015: Names for bare-board copper defects

- Status: Proposed under Jay's instruction of 2026-10-11 ("Make the program able to detect defects including, but not
  limited to, the following categories: Open Circuit, Short Circuit, Mousebite, Spur, Spurious Copper, Pin-hole /
  Missing Hole"; decisions follow industry norms). Jay's merge of this record accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-INSP-018 (new, SHOULD G1), REQ-INSP-015 (the verdict rule), ADR 0008, `aoi/core/copper.py`, recipe
  setting `copper`, `tools/dataset_check.py --copper`, docs/tests/2026-10-11-copper-defect-names.md

## Context

The engine already finds these defects on a bare board. The Golden board comparison marks every region where the board
differs from the Golden board, and on DeepPCB's public scans it found 3,092 of 3,140 labelled boxes at a 5 px Minimum
defect area (internal check, not accuracy). It named them all "Anomaly", though. An operator reviewing a call then has
to work out the defect type from the picture, and reports cannot count opens apart from spurs. Bare-board AOI names
these six types by rule, from how the copper changed against the reference. That is the norm on bare-board lines and
the six classes of DeepPCB, the public set the AI work already uses.

Of the six, the taxonomy held only Open Circuit and Short Circuit (Electrical, Critical). It is transcribed from the
PCBA defect classification table, which covers assembled boards.

## Decision

1. **Four types are added to the taxonomy, in a new Bare Board category: Mousebite, Spur, Spurious Copper and Pin-hole
   / Missing Hole, each Major.** Open Circuit and Short Circuit stay as the table has them (Critical). Major follows
   IPC-A-600, which accepts a narrowed conductor or a reduced spacing only within its class's limits, so each needs a
   person's look rather than an automatic scrap. Labellers can pick the new types too (37 in all).
2. **A recipe names copper defects only when it says what shade copper is, Light copper or Dark copper.** The new
   `copper` setting, on the Recipe Editor's Thresholds tab, is off by default. Copper's shade depends on the board and
   the lighting, and it cannot be told from the image reliably: taking the smaller class of a board as copper was right
   on only 693 of DeepPCB's 1,000 boards, and the wrong shade names about 2 % of boxes right. Assembled boards keep it
   off, so a missing part is never called a Spur.
3. **Each region outside every enabled ROI is named by rule, in a window around it.** The window's copper and
   substrate are separated at their Otsu level, on the Golden board and on the aligned board alike; the Golden board's
   whole-board level is used where the window holds only one class. Copper lost that splits a conductor is an Open
   Circuit, lost from inside copper a Pin-hole / Missing Hole, otherwise a Mousebite. Copper added that joins
   conductors is a Short Circuit, filling a hole a Pin-hole / Missing Hole, standing alone Spurious Copper, otherwise
   a Spur. A window with no clear copper, or no copper changed, stays Anomaly. So does a region on an ROI, which keeps
   the ROI's type. At most 200 regions per board are named, so a badly misaligned board cannot slow the line.
4. **Names never change a verdict.** Every name is Major or Critical, as Anomaly is, and the verdict rule (REQ-INSP-015)
   only asks whether a defect is above Minor. The regression set, stored results and the shift check are unchanged.

## Consequences

- On DeepPCB's test split (500 boards, internal check on public scans, never an accuracy claim), with Dark copper and
  a 5 px Minimum defect area, 2,609 of the 3,092 boxes found carry their own type, 84 %. Given the labelled boxes
  themselves, the rules name 2,756 of 3,140 right, 88 %. Most of the gap is alignment: DeepPCB's pairs come aligned,
  and the engine's homography moves them by up to 13 px at the corners. Opens named Mousebite (48) and mousebites
  named Spur (79) are the largest confusions. Counts are in docs/tests/2026-10-11-copper-defect-names.md.
- Nothing is measured on real bare-board photos yet: Light copper, the shade most lit photos show, is untested on a
  real board, and naming should be checked on a customer's boards before a report quotes counts by type.
- Not done here: a trained classifier for the six types, the Electrical and Bare Board types in the master samples'
  Critical list for bare boards, and naming inside ROIs. Each is a follow-up.
