# Training the comparison's thresholds on DeepPCB, 2026-10-10

REQ-TRN-018. Jay asked on 2026-10-10 to "train the program further through public pcb board images while making sure
that the program retains the ability to train from samples that the user chooses to upload and have the training data
changed or reset if the users wishes to". This record trains the golden board comparison's Pixel difference and
Minimum defect area (`aoi/core/tuning.py`) on DeepPCB's trainval split and counts its test split at the chosen pair and
at the default recipe, as the [PKU-Market-PCB record](2026-10-09-comparison-training.md) did with a seeded share held
out; the second part names the tests that keep a user's own samples, and their change or reset, as they were.

**Research data, internal check only.** As in the [public dataset check](2026-10-08-public-dataset-check.md): Jay
approved these datasets in writing on 2026-10-08 for internal training and checks; no image, box, chosen value or
model from them enters the repository or ships, and the counts below are counts on someone else's boards, never an
accuracy claim. DeepPCB's boards are scans thresholded to black and white, aligned by the dataset's authors, and most
of its labelled defects were drawn onto the scans by hand (its README), so they are close to synthetic; real boards on
a line vary far more, so the chosen pair says nothing about a customer's line.

## Why the AI model was not trained again

The AI model ran on DeepPCB on 2026-10-08 (`--ai`, in the public dataset check), per group as one board model, and
missed most of these defects: it sees a 256 px copy of the 640 px board, where a 24 to 38 px box is 10 to 15 px, and a
DeepPCB group is many crops of one board rather than repeated photos of one board model, which is what the model
learns. Nothing in that has changed, and DeepPCB has no second defect-free photo of any board, so the golden board
comparison, which this data suits, is what was trained again, on the split the dataset's authors published.

## Set-up

- Code: the S59 release-candidate stack (the head of PR #374) with this change;
  `python tools/dataset_check.py --out <scratch> --deeppcb <PCBData> --tune`.
- Machine: a cloud VM with 4 virtual CPUs and no GPU; Python 3.11.15, OpenCV 5.0.0, NumPy 2.4.6, OMP_NUM_THREADS=2.
  Nothing else ran beside it. Peak memory 602 MB; sources unchanged (every file hashed before and after).
- Data: DeepPCB from its GitHub repository, as on 2026-10-08: pairs of a defect-free template and a defective board,
  640 × 640 px, about 48 px per mm, boxes in six types.
- Split: the dataset's own. The pair is chosen on `trainval.txt` (1,000 boards) and counted on `test.txt`
  (500 boards, the split the 2026-10-08 check counted at the default recipe); no board is in both.
- Units: each boxed defect (found when a region lies within 10 px of its box), and each 512 px window of a board that
  touches no box (a false call when a region on no box lies in it); a 640 px board has up to four such windows. DeepPCB
  has no defect-free board beside each pair's template, so these windows stand in for OK boards. A region on no box in
  a window that also holds a box is not counted as a false call.
- Rule: of 14 Pixel difference values (8 to 70) and 6 areas (5 to 160 px), the pair with the fewest false calls among
  those that miss at most 1 % of the training boxes (proposed).

## Results on the 500 test boards

Chosen on the trainval boards: **Pixel difference 50, Minimum defect area 5 px** (default 45 and 40 px). On them it
missed 62 of 6,873 boxes with 271 false windows of 1,931.

| Recipe | Boxes found | False windows | Defective boards called NG | Accuracy | Precision | Recall | False call rate |
|---|---|---|---|---|---|---|---|
| Trained (50, 5 px) | 3,088 of 3,140 | 129 of 1,016 | 500 of 500 | 95.64 % | 96.0 % | 98.34 % | 12.70 % |
| Default (45, 40 px) | 2,817 of 3,140 | 105 of 1,016 | 500 of 500 | 89.70 % | 96.4 % | 89.71 % | 10.33 % |

Accuracy is the share of units judged right: (boxes found + windows left clear) / (boxes + windows). One-sided 95 %
upper bounds: missed boxes 0.0208 trained against 0.1122 default; false call rate 0.1454 against 0.1204.

The trained pair found 271 more boxes (52 missed against 323; the 2026-10-08 check counted 324 at the default
recipe on these boards, from the inspection's regions rather than the difference map's) for 24 more false windows.
Of the 14 Pixel difference values, every one below 30 floods these JPEG scans with noise (700 to 850 false windows
of 1,016 at any area), 30 and above leave 50 to 180, and the area then sets the trade: 5 px keeps the 24 px boxes,
40 px loses a tenth of them. The regions on no box were not looked at by eye this time; whether they are noise or
defects nobody labelled is not known.

## What it means

- On this data the trained pair finds 271 more of the boxed defects than the default, with the counts above, and it is
  not a claim about any line. The 2026-10-08 check's 324 misses at the default recipe on this split were mostly Open and
  Mousebite boxes of 24 to 47 px; a Minimum defect area of 5 px finds them, and on these thresholded scans the Pixel
  difference matters little once it is above the JPEG noise (30 and up; the counts are under the table).
- PKU-Market-PCB chose 15 and 20 px on 2026-10-09; DeepPCB chose 50 and 5 px. The two disagree: DeepPCB's scans need a
  Pixel difference of 30 or more against their JPEG noise and the smallest area tried for their 24 px boxes, while
  PKU-Market-PCB's photos needed a low Pixel difference and a 20 px area. One pair does not fit both datasets, let alone
  a line, and both line up to the pixel, which a line's photos do not, so the default recipe (45, 40 px) is kept: a
  board model gets its own pair from its own labelled boards, and an Engineer sets it on the Recipe Editor as an audited
  revision until a screen runs the training (REQ-TRN-018 is Partial). Changing the defaults is Jay's call.
- Accuracy here counts windows, which far outnumber defects; recall and false windows, with their counts, say more.

## A user's own samples, and changing or resetting them

The public data trains nothing that ships: `tools/dataset_check.py` is a tool outside the app, and the app's training
runs only on the samples a user imports into a board model. The tests below, run on the same code after the DeepPCB
run (165 passed in 3 min 59 s), hold that path as it was:

- Uploading: `tests/test_sample_import.py` (REQ-TRN-001: each file checked as Inspection checks it, copied into
  `images/` only, an image already imported skipped, a refused file listed with its code while the others go in, a
  stopped import keeping what went in), `tests/test_import_sheet.py` (the sheet imports into the board model it was
  opened for), `tests/test_no_freeze.py` (adding samples and importing a folder do not freeze the screen).
- Changing: `tests/test_services_api.py` (REQ-TRN-007: Mark NG and Remove skip only the reference sample),
  `tests/test_logs_history.py::test_req_log_003_only_an_admin_removes_a_sample`, `tests/test_confirmations.py` (Enter on
  Remove samples keeps them; the removal asks first), `tests/test_datasets.py` and `tests/test_freeze_screen.py`
  (REQ-TRN-005: a frozen dataset version is locked and verified, so a later change to the samples never changes what a
  version trained on), `tests/test_train_from_version.py` (REQ-TRN-007: training reads only the version picked),
  `tests/test_training_job.py` (REQ-TRN-008: one training at a time, and a cancelled one keeps the active AI model).
- Resetting: `tests/test_model_versions.py` and `tests/test_model_go_live.py` (REQ-TRN-010: Roll Back restores the
  earlier AI model and golden board and names its version), `tests/test_dataset_stores.py` and
  `tests/test_dataset_stores_screen.py` (REQ-TRN-017: Shred store deletes a store's contents for good, resuming if
  interrupted), `tests/test_demo.py` and `tests/test_demo_ui.py` (REQ-SET-007: Reset Demo puts the demo workspace back
  and leaves production untouched, asking first).

The tool's output stays in the session scratchpad, out of git.
