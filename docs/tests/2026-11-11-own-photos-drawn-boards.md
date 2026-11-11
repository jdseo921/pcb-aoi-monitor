# A customer's own photos: what was changed and what was measured, 2026-11-11

Issues #460 and #461, with evidence for #453; #462 stays open. Jay's request, verbatim: "Try to look for and address
shortcomings so that a client can install and run the program properly with their own set of photoes. Make them happen
step by step and do not stop until finshed. When done, merge in order and push everything to main and see if it is
ready for demonstration recording." and, the same day, "Allow the user to train the program with their own board
samples, view the state of training itself, and manage/reset the metrics to default."

Every number here is a count on boards drawn by a program. None is an accuracy, and none is quoted as one. The public
photographs of the 2026-11-04 and 2026-11-05 records could not be reached from the machine that made this change, so
**nothing here was measured on photographs**; the first thing to do with this version is to repeat those two records
(`tools/proxy_validation.py`, `tools/proxy_scenarios.py`).

## What was wrong

A new customer's first hour was walked through the real window on a fresh workspace: the first Admin, the first board
model, a folder of 81 good and 20 defective photos with a Thumbs.db, a text file, a file that is no picture and a
Korean file name in it, Train, then boards the program had not seen. The guide's three steps worked as written. What
the engine then did with photos that differ as photographs do was the fault, in six places:

| # | What happened | Why | Change |
|---|---|---|---|
| 1 | A photo 15 % brighter or darker, or tinted, was NG | Neither check allowed for the light | `imaging.match_light`: brightness, colour cast, black level and light from one side are fitted and taken out; a photo within 2 % is left as taken |
| 2 | A board turned 2° or shifted was NG or WARN | The warp's empty border was read as a defect by both checks | `imaging.conform`: the Golden board's pixels where the photo showed none; nothing counted there or at that edge; under 95 % of the frame shown is a WARN that says so |
| 3 | A 5 MP photo of a 0.3 MP Golden board was WARN | ORB's pyramid spans 3.6 times; the warp skipped pixels | matched at the Golden board's scale, averaged down before the warp |
| 4 | Good boards were flagged at their corners | The homography's eight numbers fitted the matches' noise: up to 9 px off at a corner | `imaging._simplest`: a turn, shift and scale when they explain as many matches to 2 px |
| 5 | Bright parts of a brighter photo were flagged | A value the camera clipped cannot be corrected | a clipped value counts only against a Golden board on the side the clipping did not hide |
| 6 | Good boards were WARN with every check OK | The AI model's pixel threshold lay at 0.6 of the image threshold: a good board past that had a "region" | the pixel threshold is calibrated on the region levels of the good boards held out (`compare.region_level`), by the image threshold's rule |

Two more changes prepare for photographs and could not be shown to matter on drawings: the Golden board's file now
carries a per-pixel tolerance learned from the training good boards (#461), and a first AI model's untouched recipe
takes its similarity threshold from them when the default 0.80 is above what they score (0.47 at the median on VisA).

## Counts

**The synthetic regression set** (`tests/regression`, the compare step): 20 of 20 good boards OK before and after. 13
of 20 defective boards NG before, 14 after: `ng_02_misalignment` and `ng_04_contamination` newly found;
`ng_11_contamination` newly missed, a 42 px region that had passed the threshold only because its photo was 4 %
brighter than the Golden board.

**Boards drawn to vary** (`tools/varied_boards.py`: a date code on each part and a serial-number label on each board,
solder that shines differently, a mottled surface, parts a pixel or two off, placement ±1.5° and ±8 px, light ±10 %
with a 4 % gradient and ±8 grey levels of black level, focus and noise). A run the size of the first-run guide's: 31
good boards and 14 defective to train on (8 of the good ones held out to calibrate), 60 rounds at 256 px; then 50 good
and 35 defective boards never seen, five of each of seven defect types.

| Engine | Good boards (50): OK / WARN / NG | Defective boards (35): NG / WARN / OK |
|---|---|---|
| Before (`9a19877`) | 31 / 11 / 8 | 28 / 2 / 5 |
| This version, pixel threshold as it was | 35 / 13 / 2 | 30 / 1 / 4 |
| This version | 45 / 3 / 2 | 30 / 0 / 5 |

- Before, the 19 good boards called were called by the AI score (9), a difference region (6) or an AI region alone (6;
  a board can have more than one). With this version the 5 still called are all the AI score's: its threshold comes
  from eight boards held out, and 2 of 50 new good boards scored above it, 3 within its WARN band. That is #462, open.
- The 5 defective boards passed are the five solder bridges, drawn 3 px wide: below the recipe's minimum defect area
  at this photo size. One was WARN for an AI region with the old pixel threshold; that is what the new one costs here.
- The comparison alone, on 40 unseen good boards with 31 to train on: 3 flagged before change 4 and 5, 0 after, with
  or without the tolerance; the tolerance cost no defect (31 of 42 found by the comparison both ways).

**What still stops a new customer.** In the walk the first shift check failed, and Inspection refused every board: one
master sample, a solder bridge, was judged OK. That is the interlock working: the station found that it cannot tell a
known-defective board from a good one. The guide's Train screen now names the sample and says what to do (#453); the
tester guide's new section 7 says what photos to take and what a few-pixel defect means.

## Not done

- #462: the AI image threshold and its WARN band on few held-out boards. On these drawings it is the last source of
  calls on good boards (5 of 50).
- No photograph was judged with this version. G2 on the factory's own boards stands as it did.
- The Korean strings of the new lines are untranslated, as 1,643 others are.
