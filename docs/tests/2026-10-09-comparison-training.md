# Training the comparison's thresholds on PKU-Market-PCB, 2026-10-09

REQ-TRN-018. Jay asked on 2026-10-09 for training "so that the false positives are minimized; aim for 95% accuracy".
This record trains the golden board comparison's Pixel difference and Minimum defect area (`aoi/core/tuning.py`) on
70 % of PKU-Market-PCB and counts the 30 % held out, at the chosen pair and at the default recipe.

**Research data, internal check only.** As in the [public dataset check](2026-10-08-public-dataset-check.md): Jay
approved these datasets in writing on 2026-10-08 for internal training and checks; no image, box, chosen value or
model from them enters the repository or ships, and the counts below are counts on someone else's boards, never an
accuracy claim. PKU-Market-PCB's defects were drawn onto photos of 10 boards: each defective photo is its board's
defect-free photo with the defects edited in, so the boards line up to a fraction of a pixel and outside the defects
differ only by JPEG noise. Real boards on a line vary far more, so the chosen pair says nothing about a customer's line.

## Why the AI model was not trained

The AI model trains per board model on at least 2 OK images (AOI-TRN-002); PKU-Market-PCB has one defect-free photo of
each board, and the model sees the board at 256 px, where a 50 to 120 px defect on a 3,000 px photo is 4 to 10 px. The
golden board comparison, which this data suits, is what was trained.

## Set-up

- Code: main at 7bb8648 with this change; `python tools/dataset_check.py --out <scratch> --pku <PCB_DATASET> --tune`.
- Machine: a cloud VM with 4 virtual CPUs and no GPU; Python 3.11.17, OpenCV 5.0.0, NumPy 2.4.6, OMP_NUM_THREADS=2.
  The full test suite ran beside it, so its times are not a benchmark. Peak memory 1,290 MB; sources unchanged.
- Data: 693 defective photos (6 types, 2,953 boxes) copied from Jay's pcb-dataset folder; `rotation/` left out.
- Split: per board and defect type, a seeded 30 % of the photos held out (`held_out`, seed 0): 483 photos with 2,052
  boxes to train, 210 with 901 boxes held out.
- Units: each boxed defect (found when a region lies within 10 px of its box), and each 512 px window of a photo that
  touches no box (a false call when a region on no box lies in it). PKU-Market-PCB has no defect-free photo besides
  each board's Golden board, so these windows stand in for OK boards. A region on no box in a window that also holds a
  box is not counted as a false call.
- Rule: of 14 Pixel difference values (8 to 70) and 6 areas (5 to 160 px), the pair with the fewest false calls
  among those that miss at most 1 % of the training boxes (proposed).

## Results on the 210 held-out photos

Chosen on the training photos: **Pixel difference 15, Minimum defect area 20 px** (default 45 and 40 px). On them it
missed 13 of 2,052 boxes with 31 false windows of 10,516.

| Recipe | Boxes found | False windows | Defective photos called NG | Accuracy | Precision | Recall | False call rate |
|---|---|---|---|---|---|---|---|
| Trained (15, 20 px) | 895 of 901 | 9 of 4,558 | 210 of 210 | 99.73 % | 99.0 % | 99.33 % | 0.20 % |
| Default (45, 40 px) | 487 of 901 | 4 of 4,558 | 162 of 210 | 92.34 % | 99.2 % | 54.05 % | 0.09 % |

Accuracy is the share of units judged right: (boxes found + windows left clear) / (boxes + windows). One-sided 95 %
upper bounds: missed boxes 0.0131 trained against 0.4874 default; false call rate 0.0034 against 0.0020.

The trained pair found 408 more defects and called all 48 defective photos the default called OK, for 5 more false
windows. By eye, every one of the 14 regions on no box in the held-out photos at the trained pair (in 14 photos, 9 of
them in windows counted) is an edit that the photo has and its Golden board does not: a missing hole, bites, shorts,
spurs and copper, left unboxed in the dataset's annotations. So on this data the false calls left are unlabelled
defects, not noise (judged by eye from crops, not checked against the dataset's authors).

## What it means

- Jay's aim of 95 % is met on this data by the trained pair, with counts above, and it is not a claim about any line.
- The default recipe is kept: 15 and 20 px suit photos that line up to the pixel, and would flag far more on photos
  taken one by one on a line. A board model gets its own pair from its own labelled boards, and an Engineer sets it on
  the Recipe Editor as an audited revision until a screen runs the training (REQ-TRN-018 is Partial).
- Accuracy here counts windows, which far outnumber defects; recall and false windows, with their counts, say more.

The tool's output and the scripts that drew the crops stay in the session scratchpad, out of git.
