# Naming bare-board copper defects on DeepPCB, 2026-10-11

REQ-INSP-018, ADR 0015. Jay asked on 2026-10-11 for the program to detect Open Circuit, Short Circuit, Mousebite,
Spur, Spurious Copper and Pin-hole / Missing Hole. The golden board comparison already finds them; this record counts
how often the new rules (`aoi/core/copper.py`) give each found box its own name.

**Research data, internal check only.** As in the [public dataset check](2026-10-08-public-dataset-check.md): Jay
approved DeepPCB in writing on 2026-10-08 for internal training and checks; no image, box or count from it enters the
product, and the counts below are counts on someone else's boards, never an accuracy claim. DeepPCB's boards are scans
thresholded to black and white with copper dark, and most of its defects were drawn on by hand, so they are close to
synthetic. Nothing here says how the names do on a customer's photos.

## Set-up

- Code: branch `feat/REQ-INSP-018-copper-defect-types`, on the shift check (#386).
- Commands: `python tools/dataset_check.py --out <scratch> --deeppcb <PCBData> --min-area 5 --copper dark`, and the
  same without `--copper` for the time per board. The default recipe otherwise, AI check off; a box is found when a
  region lies within 10 px of it.
- Machine: a cloud VM with 4 virtual CPUs and no GPU; Python 3.13.16, OpenCV 5.0.0, NumPy 2.4.6. Peak memory 825 MB;
  sources unchanged (every file hashed before and after).
- The rules were set on the trainval split (1,000 boards) and counted once on the test split (500 boards) below.

## Results on the test split (500 boards, 3,140 labelled boxes)

Every board was NG with and without names, and the same 3,092 boxes were found: naming changed no verdict and no box.

| Labelled type | Found | Named right | Named most often otherwise |
|---|---|---|---|
| Open | 638 | 494 | Mousebite 48, Spurious Copper 41 |
| Short | 462 | 433 | Spur 28 |
| Mousebite | 583 | 381 | Spur 79, Anomaly 74 |
| Spur | 481 | 440 | Spurious Copper 36 |
| Spurious copper | 459 | 437 | Anomaly 11 |
| Pin-hole | 469 | 424 | Anomaly 20, Spur 15 |
| All | 3,092 | 2,609 | |

"Named right" counts a found box when any region over it carries its type; the last column names the first region over
it. Given the labelled boxes themselves rather than the regions the comparison found, the rules name 2,756 of 3,140
right. Most of the difference is alignment: the dataset's pairs come aligned, and the engine's homography moves some
boards by up to 13 px at a corner, which turns a notch into a notch plus a sliver. With Light copper, the wrong shade
for these scans, 62 of 3,140 labelled boxes are named right.

Time per board: median 79 ms with names, 61 ms without; 95th percentile 162 ms and 106 ms. At most 200 regions per
board are named. With names off, as every recipe is until an Engineer sets them, nothing runs.

## What this does not show

- Light copper and real photos: no bare-board photo with labelled defects was available. Check the names on a
  customer's boards before a report quotes counts by type.
- The 1,969 regions on no labelled box (at a 5 px Minimum defect area) are named too, mostly Spur; on a line they are
  false calls whatever their name, which the review (REQ-INSP-013) counts.
