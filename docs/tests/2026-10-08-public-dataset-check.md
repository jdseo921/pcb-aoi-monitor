# Public dataset check, 2026-10-08

Plan stage S30, 3 of 3. Before customer photos arrive, `tools/dataset_check.py` runs v0.2's golden-board comparison
and its AI model on DeepPCB, a public research dataset of PCB defects, against REQ-INSP-014, with time per board
(REQ-INSP-007) and training time and memory (REQ-TRN-007) measured on the way.

**Research data, internal check only.** Jay approved this use in writing on 2026-10-08 (04:06Z): "Only use those files
to train for now - i will add customer photos later." Jay's words name training; reading them as covering these checks
too is our interpretation, as the checks are internal and nothing from them ships. No image, box or trained model is
in this repository. These are counts on someone else's boards, scanned and thresholded to black and white, and
DeepPCB's README says its authors "manually argument some artificial defects on each tested image": most labelled
defects were drawn onto the scans by hand, so these boards are close to synthetic. The counts are not accuracy and
are never quoted as accuracy.

## Set-up

- Code: S30 parts 1 and 2 (`tools/dataset_check.py`, in review when it ran) on main as of 2026-10-08, whose inspection
  engine they do not change. Default recipe; the golden-board comparison with the AI check off, then the AI model
  alone. The run used the tool before part 2's review fixes, which added `--min-area`.
- Machine: a cloud VM (KVM) with 4 virtual CPUs (Intel Xeon, 2.1 GHz), 16.9 GB of memory and no GPU; Python 3.11.15,
  PyTorch 2.14.1 on the CPU, OpenCV 5.0.0, NumPy 2.4.6. The run's command, in the session's transcript and in no
  saved file, set OMP_NUM_THREADS=2 and MKL_NUM_THREADS=2; its results.json held only the system and Python version,
  so the rest was read from the VM. The tool now records them, its arguments and those two settings; its reruns below,
  with the same thread settings on the same VM, recorded PyTorch on 2 threads and OpenCV on 4. It is not the
  reference PC.
- Data: DeepPCB from its GitHub repository (last change 2018-12-19), assumed to be the source of the copy in Jay's
  pcb-dataset folder: the laptop run below found the same 500 pairs, 3,140 boxes and misses per type there (not
  compared file by file). Its test split: 500 pairs of a defect-free template and a
  defective board, 640 × 640 px, aligned and thresholded by the dataset's authors, about 48 px per mm (its README),
  with 3,140 labelled boxes in six types. The smallest box is 24 px (0.5 mm) on its longer side, the median 38 px
  (0.8 mm), so the run cannot test REQ-INSP-014's floor of 4 px.
- Sources unchanged: the run hashed the 3,000 images of both splits twice, both times after its checks, so that
  comparison could not catch a change the run made; `git status` in the dataset's clone is clean after all the runs.
  The tool now hashes before the checks too (S30 part 2's review fix), and its reruns below found no file changed.
- PKU-Market-PCB is on Jay's laptop only and ran there on 2026-10-09 (below). It has one defect-free photo per board,
  so it gets the golden-board comparison only.
- A labelled box counts as found when a difference region lies within 10 px of it.

## Golden-board comparison, AI check off

All 500 defective boards were NG. Of 3,140 labelled boxes, 324 were missed (one-sided 95 % upper bound on the miss
rate 0.113), and 786 regions lay on no box. No defect-free board went through the comparison, so a region on no box
is not a count of false NG; whether one is noise or a defect nobody labelled was not checked.

| Type | Boxes | Found | Missed | 95 % upper bound on misses |
|---|---|---|---|---|
| Open | 659 | 483 | 176 | 0.297 |
| Mousebite | 586 | 520 | 66 | 0.136 |
| Short | 478 | 432 | 46 | 0.121 |
| Spur | 483 | 456 | 27 | 0.076 |
| Copper | 464 | 459 | 5 | 0.023 |
| Pin-hole | 470 | 466 | 4 | 0.019 |

By the box's longer side, it missed 119 of 357 boxes of 24 to 31 px, 199 of 2,170 of 32 to 47 px and 6 of 613 of
48 px or more. A box marks where the defect is, not its width.

The same boards with only the Minimum defect area changed, first by a script in the session, then rerun with the
tool's `--min-area` (same counts):

| Minimum defect area | Missed boxes | Regions on no box |
|---|---|---|
| 40 px (default) | 324 | 786 |
| 20 px | 125 | 1,175 |
| 10 px | 71 | 1,550 |
| 1 px | 48 | 1,969 |

At 1 px, 276 of the 324 boxes missed at 40 px were found, each by a region overlapping the box itself, whose largest
region there was 5 to 39 px in area (median 28). The other 48 are lost before the area test: 4 reach into the 10 px
border the comparison leaves out, the rest to the 5 × 5 blur, the difference threshold of 45, the ±2 px shift tolerance
or the 3 × 3 clean-up (not traced per box). A second rule, keeping the 1 px run's regions whose bounding box is 8 px or
more on its longer side, missed 195 boxes at about the same number of regions on no box (1,166 against 1,175 at 20 px),
so it did worse than the area; that filter and the overlap figures came from scripts in the session, not in the
repository.

Inspection alone took a median 62.8 ms per board (95th percentile 111.6 ms); a golden-only run earlier the same morning
gave 71.2 ms (153.7 ms), and the four reruns at 40, 20, 10 and 1 px medians of 139.6 to 162.1 ms (95th percentiles 315.5
to 375.8 ms) on the same VM, while other test runs loaded it (load averages of 15 to 28 then, on 4 virtual CPUs). The
load was not controlled, so these times bound REQ-INSP-007 loosely and are not a benchmark.

## AI model alone

Per DeepPCB group, as one board model: 20 distinct templates of its trainval split (seeded), 5 defective boards to
calibrate, 60 epochs at 256 px, then the group's test boards scored. Four groups have no trainval boards and were left
out (332 test boards), leaving 7 groups and 168 test pairs.

- The 168 templates: 158 OK, 9 Warning, 1 NG (upper bound 0.028 on NG).
- The 168 defective boards: 115 OK, 31 Warning, 22 NG (upper bound 0.744 on OK).
- Training per group: median 142 s, 95th percentile 308 s; scoring a board: median 16.5 ms (21.7 ms).
- Peak memory of the whole run: 1,027 MB.

The AI model misses most of these defects, which says little about real boards: it sees a 256 × 256 copy of the
640 × 640 board, so a 24 to 38 px box shrinks to 10 to 15 px, and a DeepPCB group is many different crops of a board,
while v0.1's model learns each pixel's normal variation over repeated photos of one board model (inferred, not
tested).

## Second run, on Jay's laptop, 2026-10-09

The tool from #297 at its last commit before main's S28c to S35 were merged into it, with `--deeppcb --pku --ai` and
its defaults (Minimum defect area 40 px, 20 OK images per training, seed 0), read Jay's pcb-dataset folder in place.
Its hashes after the checks matched those before, so no source file changed. The laptop: Intel Core Ultra 7 255H (16
threads), 31.5 GB of memory, no GPU, Windows 11 Home 25H2, Python 3.14.2, PyTorch 2.14.1 on the CPU, OpenCV 5.0.0; not
the reference PC. Its `results.json` and `summary.md` stay on the laptop, and the counts below are copied from the
summary reported from it. S28c to S35 changed no verdict on the synthetic regression set
(`tests/regression/expected.json` is unchanged), and the tool sets neither judging input they added: a board model's
scale and its override of the AI score threshold.

DeepPCB, golden board, AI check off: the same as the cloud run, all 500 boards NG and 324 of 3,140 boxes missed with the
same misses per type, but 793 regions on no box against 786 (the difference was not traced). Time per board: median 53
ms, 95th percentile 82 ms.

PKU-Market-PCB, golden board, AI check off: 693 defective photos, about 2,240 to 3,056 px wide (4 to 7 MP), each judged
against its board's defect-free photo. 517 were NG and **176 OK** (one-sided 95 % upper bound on boards called OK
0.283). Of 2,953 labelled boxes, **1,424 were missed** (upper bound 0.498), and 25 regions lay on no box. Time per
board: median 754 ms, 95th percentile 993 ms.

| Type | Boxes | Found | Missed | 95 % upper bound on misses |
|---|---|---|---|---|
| Missing hole | 497 | 487 | 10 | 0.034 |
| Mouse bite | 492 | 205 | 287 | 0.620 |
| Open circuit | 482 | 190 | 292 | 0.643 |
| Short | 491 | 227 | 264 | 0.575 |
| Spur | 488 | 186 | 302 | 0.655 |
| Spurious copper | 503 | 234 | 269 | 0.572 |

Why each box was missed was not traced. The laptop run's reading (inferred): these defects are about 30 to 70 px
across, and many fall under the 40 px Minimum defect area or within the comparison's alignment tolerance. The
`--min-area` what-if was not run on PKU-Market-PCB.

DeepPCB, AI model alone, trained as in the cloud run with the same seed: of the 168 templates, 148 OK, 17 Warning and 3
NG (upper bound 0.046 on NG); of the 168 defective boards, **107 OK**, 15 Warning and 46 NG (upper bound 0.699 on OK),
against 115 OK, 31 Warning and 22 NG in the cloud, so training did not repeat across the two machines (cause not
traced). Training per group: median 75 s. Peak memory was not read: on Windows the tool's read failed and its summary
said 0.0 MB, fixed in the same PR as this section.

## What it means

- REQ-INSP-014: not measurable here (not the locked validation set, not the customer's camera). On this data the
  default 40 px Minimum defect area missed 324 of 3,140 labelled defects, 242 of them opens (176) and mousebites (66);
  a smaller area found more boxes and left more regions on no box. On PKU-Market-PCB's 4 to 7 MP photos, the weak
  case, it missed 1,424 of 2,953 and called 176 of 693 defective boards OK; only missing holes were found most of the
  time (487 of 497). ADR 0008 (proposed) puts the default to Jay.
- REQ-INSP-007: at 0.4 MP, inspection alone stayed under 0.4 s per board at the 95th percentile on this VM, even loaded;
  the budget is set at the customer's resolution on the reference PC, which the resolution test and the CI performance
  job measure. On Jay's laptop, inspection alone of PKU-Market-PCB's 4 to 7 MP photos, AI check off, took a median 754
  ms and 993 ms at the 95th percentile: inside 1 s, with nothing left for the AI check or for showing the verdict, which
  the budget also covers (inferred).
- REQ-TRN-007: 20 images, 640 px resized to 256 px, trained in a median of 142 s per group (95th percentile 308 s) on
  2 PyTorch threads of this VM, in at most 1,027 MB; the budget's 50 images at the customer's resolution on the
  reference PC is still unmeasured. On Jay's laptop the same training took a median 75 s per group.

The tool's output (counts, manifest, summary) and the analysis scripts stay in the session scratchpad and out of git.
