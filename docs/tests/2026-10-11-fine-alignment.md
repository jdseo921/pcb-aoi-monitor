# Fine alignment and learned thresholds: false calls on DeepPCB and time per board, 2026-10-11

REQ-RCP-007 and REQ-TRN-018, ADR 0017. This record counts what fine alignment and the thresholds that Learn From
Labelled Boards chooses do to missed defects and false calls on a public bare-board dataset, and times fine alignment
on the synthetic regression boards.

**Research data, internal check only.** As in the [public dataset check](2026-10-08-public-dataset-check.md): Jay
approved DeepPCB in writing on 2026-10-08 for internal training and checks; no image, box, chosen value or model from it
enters the product, and the counts below are counts on someone else's boards, never an accuracy claim. DeepPCB's boards
are scans thresholded to black and white, and most of its defects were drawn on by hand, so they are close to
synthetic. The timings are on synthetic boards, which are never quoted as accuracy either. Nothing here says how the
app does on a customer's photos, and nothing was measured on the reference PC (ADR 0011).

## Set-up

- Code: branch `feat/REQ-TRN-018-learn-thresholds`. The engine (`aoi/core/tuning.py`, `imaging.py`, `inspector.py`,
  `compare.py`, `recipe.py`) is as committed in c59f6b1; later commits on the branch change no engine file.
- Machine: a cloud VM with 4 virtual CPUs (Intel Xeon at 2.10 GHz) and no GPU; Python 3.13.16, OpenCV 5.0.0,
  NumPy 2.4.6. AI check off throughout: the comparison alone.
- Counting, as `AppContext.learn_comparison` counts: each board is aligned and compared with `tuning.board_tables`, at
  every Pixel difference and Minimum defect area tried, with fine alignment off and on. A boxed defect is found when a
  region the comparison finds lies within 10 px of it. The rest of the board is cut into windows of up to 512 x 512 px
  (a 640 px DeepPCB board gives four); a window that touches no boxed defect is a false call when the comparison found
  a region in it.
- The setting was chosen with `tuning.choose_setting` on the trainval split (1,000 boards, 6,868 boxes) and counted
  once on the test split (500 boards, 3,140 boxes). The scripts are kept outside the repository with the data.
- Timing: `Inspector.inspect` on the 40 synthetic regression boards (`tests/regression`), resized with cubic
  interpolation to 640 x 480 (0.3 MP) and 2592 x 1944 (5 MP) as `tests/perf` resizes them, one warm-up board, the
  fastest of 3 passes per board. Nothing else ran on the machine meanwhile.

## Results on DeepPCB's test split (500 boards, 3,140 boxed defects)

The setting chosen on trainval was Pixel difference 50, Minimum defect area 5 px, fine alignment on.

| Setting | Boxed defects found | False calls (windows with no boxed defect) |
|---|---|---|
| Default recipe (45, 40 px), fine alignment off | 2,822 of 3,140 | 103 of 1,012 |
| Default recipe (45, 40 px), fine alignment on | 2,820 of 3,140 | 47 of 1,014 |
| Learned pair (50, 5 px), fine alignment off | 3,093 of 3,140 | 127 of 1,012 |
| Learned pair (50, 5 px), fine alignment on (chosen) | 3,092 of 3,140 | 62 of 1,014 |

- The learned pair misses 48 of 3,140 boxed defects (95 % upper bound 1.9 %) against the default's 318 of 3,140
  (upper bound 11.1 %).
- Fine alignment roughly halves the false calls at either pair (127 to 62, 103 to 47) and changes the boxes found by
  one or two. The number of windows differs by two because the boxes are mapped onto the Golden board through each
  alignment, so a window at a box's edge can touch it under one and not the other.
- On trainval, where the setting was chosen, the chosen setting found 6,811 of 6,868 boxed defects with a false call
  in 171 of 1,922 windows.

## Time per board (synthetic regression boards, 40 each)

| Size | Fine alignment off: median, 95th percentile | On: median, 95th percentile | Added at the median |
|---|---|---|---|
| 0.3 MP (640 x 480) | 32.7 ms, 39.0 ms | 85.2 ms, 101.2 ms | 52 ms |
| 5 MP (2592 x 1944) | 472.5 ms, 528.3 ms | 581.9 ms, 627.7 ms | 109 ms |

Fine alignment works on the boards scaled to at most 1,024 px, so its cost grows little with the image: about 0.1 s
per board at the sizes measured (`imaging.FINE_COST_MS`, which the Recipe Editor's note names). With it on, the 5 MP
board stays within REQ-INSP-007's 1 s on this machine with the AI check off; the AI check, reading the file, saving
and display come on top, and the reference PC's figures are still to be measured (release gate box 2).

## What this does not show

- Any figure on a customer's boards or photos, or with the AI check on.
- Whether the chosen setting carries over from DeepPCB's scans to photographs; Learn From Labelled Boards chooses on
  each board model's own labelled boards for that reason.
- Time on the reference configuration of ADR 0011.
