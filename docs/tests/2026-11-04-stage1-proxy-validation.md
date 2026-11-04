# Stage 1 proxy validation on public datasets, 2026-11-04

Issue #452 (REQ-TST-008, test only). The factory's photographs have not arrived yet, so this test uses public PCB images
as a stand-in. It runs Stage 1 end to end through the app's own path, on several test sets, and records how the
program behaves. `tools/proxy_validation.py` drove every run. Nothing under `aoi/` changed, and
`tests/regression/expected.json` is byte-identical to `b5bf413`.

**Jay's approval, verbatim:** "Jay approved on 2026-11-04 the use of the public datasets named in this record for
internal Stage 1 testing only. No image, box, mask or trained model from them enters the repository or ships, and no
result from them is quoted as accuracy."

Every number below is a count from an internal test on someone else's boards, never an accuracy claim. Each bound is
the one-sided 95 % Clopper-Pearson upper bound (`upper_95` in `tools/dataset_check.py`).

## Summary

- **Does Stage 1 work end to end on real photos of assembled boards?** The path runs: import with boxes, freeze,
  lock, train, activate, inspect, AI Model Test, result files and exports. It completed without a crash or an
  unexpected error in all 13 VisA runs. The verdicts do not work.
  - With the default recipe, every good board in every run was NG (3,250 of 3,250). The golden-board comparison
    flags each photo: on pcb1 the median SSIM was 0.47 against a 0.80 limit, with 92 difference regions against 0.
  - As a result, the shift check fails on its known-OK master sample. The station refuses to inspect until an Admin
    turns the check off (#453).
  - Every defective board was NG too, and 1 of 390 had no defect box on its mask (pcb1, 400 good). Being NG says
    nothing about detection when every board is NG.
- **Which defect kinds does it do well and badly on?** The golden-board comparison cannot tell kinds apart here,
  since it flags every board. The AI check on its own is weak on every kind.
  - In the 150 good runs of all four categories, it passed 31 of 52 Damaged Component boards, 12 of 24 Missing
    Component, 9 of 20 Scratch and 7 of 15 Bent Lead.
  - It flagged all 6 Contamination and all 3 Misalignment boards, but those sit mostly in pcb4. On pcb4 the AI check
    also flags 25 of 250 good boards.
  - Its threshold is set by the single highest-scoring good calibration image (#454).
- **How many good boards must a customer send?** No count gave a working station here.
  - The app asks for 70 good images (20 to train, 50 held out; REQ-TRN-021). Each run here trained on 70, 150 or 400
    good images and locked 50 more, so its "70" is 120 images in all.
  - More good images cut the AI check's false calls: pcb2 went from 37 to 2 of 250 between 70 and 400, and pcb4 from
    29 to 6.
  - They did not make it catch more. At 70, 150 and 400, pcb1 passed 14, 29 and 27 of 30 defective boards and pcb4
    passed 1, 0 and 6, because more calibration images can raise the highest good score that sets the cut (#454).
  - Until #453 and #454 are settled, no count of good boards gives a working station on photos like these.
- **How fragile is it to photo changes?** The golden-board comparison already fails on unaltered photos, so the
  changes could not make it worse.
  - JPEG 70, ±2° rotation, a 20 px shift and a slight blur moved the AI scores of good boards little (median 2.4 to
    2.8, against 2.65 unaltered).
  - Resizing to 5 MP moved them more: the median rose to 2.87, the p95 from 5.21 to 6.56, and the AI check flagged 5
    of 250 good boards against none.
  - Brightness moved them most: the median rose to 3.6 at +15 % and 4.9 at −15 %. Lighting is the change to hold
    steady at the station. Nothing beyond ±15 % was tried.
- **What this does and does not tell us about the factory's boards:**
  - VisA's photographs are not the factory's. The light, camera, boards and defects all differ, and its masks mark
    anomalies, not the factory's defect types.
  - The test shows that the path a customer takes runs to the end. It also shows two behaviours on photos with
    ordinary photo-to-photo variation: one stops the station (#453), the other lets defects through the AI check
    (#454).
  - It does not show whether the factory's camera and lighting give images steady enough for the default comparison,
    nor how either check counts the factory's defects. Only G2 on the factory's boards can show that.

Issues opened: #453 (the golden-board comparison on photos and the shift check), #454 (the AI image threshold).

## Set-up

- **Code:** `main` at `57214ae`, with this test's tools on the `test/452-*` branches. Default recipe (Pixel difference
  45, Minimum defect area 40, SSIM 0.80, changed area 0.5 %, no difference region allowed, WARN ratio 0.8, AI check
  on). AI model settings at their defaults: 256 px input except where stated, 60 epochs, seed 0.
- **Path:**
  - `AppContext` throughout: a board model in a new dataset store; import of an `ok/` and `ng/<type>/` folder with a
    Pascal VOC file beside each NG image (a box per mask blob of 4 px or more).
  - A Validated freeze was tried first and refused with AOI-TRN-020 (a second person must check the NG labels). The
    test then froze a Trial version (one person), locked the validation set with seed 0, trained as an Engineer,
    activated, and ran AI Model Test on the locked set.
  - The shift check ran next, then each held-out board went through `InspectionCycle`. The user signed in was the
    one of the step before: the Admin who had turned the shift check off (set A), the Engineer (set E's drawn boards)
    or the Operator (set B). The tool now signs in the Operator for this step. The user changes the name on the
    records, not a verdict.
  - Result files were checked against `docs/schemas/result-file.schema.json` with the repository's own checker.
  - The exports ran on the real AI Model Test page, offscreen, as an Admin: Validation Report, Export Report (PDF),
    Export CSV and Export Image Overlays.
  - `tools/trainable.py` was not used.
- **Machine:** a cloud VM, 4 virtual CPUs (Intel Xeon, 2.1 GHz), 16.9 GB of memory, no GPU. Python 3.13.18, NumPy
  2.4.6, OpenCV 5.0.0, PySide6 6.11.2, PyTorch 2.14.1 on the CPU, with 4 threads for PyTorch and 4 for OpenCV.
  - PyTorch came from PyPI (`2.14.1+cu130`), because the CPU wheel index named in `requirements-torch-cpu.lock` was
    blocked from the VM. It is the same version number, run on the CPU, but a different build installed without the
    lock's hashes, so the lock was not honoured for PyTorch on this VM.
  - It is not the reference PC. Times are for comparison between runs only.
- **Data, licences and hashes:**

| Set | Source | Licence (read before download) | Files | Digest of `sha256sum` over the sorted files |
|---|---|---|---|---|
| VisA pcb1 to pcb4 | `https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar` (1,929,840,640 bytes, sha256 `2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362`), pcb1 to pcb4 extracted | CC BY 4.0 for the data (its README); the code repository is Apache 2.0 | 1,205 / 1,202 / 1,207 / 1,206 | see below |
| DeepPCB | `https://github.com/tangsanli5201/DeepPCB` at `08e98c4` (2018-12-19) | MIT | 4,503 | see below |
| PKU-Market-PCB | not downloaded | none stated | – | – |
| MVTec AD | not downloaded | CC BY-NC-SA 4.0, non-commercial, excluded by Jay | – | – |

  - The digests are `find <folder> -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum`, run in the data
    folder:
    - pcb1 `d0748e8f5869c726c7daba21d9e98431ee14502e4431d81be58646169a60a5a7`
    - pcb2 `adc2beca6f82ae0c5ef4bffd76d781d1f3eeafeb20323959003da56af4f4d97d`
    - pcb3 `c5f37ad727d0a9d545a1de19cf1bd97e7757043b218633a516d698ac7c1396ba`
    - pcb4 `4d58fcec76328743ffbf5bd007ad447893b76afa177d65f7e33f29ab4bd4686b`
    - DeepPCB `PCBData` `c52563fc74faa6e21e8892e479d4e9908339687d089c0fbaebf4705cded10052`
  - VisA is credited as its licence asks: Y. Zou, J. Jeong, L. Pemula, D. Zhang and O. Dabeer, "SPot-the-Difference
    Self-Supervised Pre-training for Anomaly Detection and Segmentation", ECCV 2022 (arXiv:2207.14315), Amazon.
  - Each VisA category has about 1,000 normal and 100 anomalous photos (1404 × 1070, 1562 × 960 or 1358 × 1104 px)
    with an anomaly mask each.
  - The tool hashed every source file before and after each set, and found them unchanged (`sources_unchanged: true`
    in each set's JSON). The digests above were taken mid-way through the work and again after the last
    run, and were the same both times.
  - Data, workspaces and outputs were kept under `/home/claude/data` and `/home/claude/runs`, outside the repository.
- **Counting:**
  - A defective board counts as found when it is judged NG or WARN and one of its defect boxes overlaps its mask,
    after the mask is warped into the Golden board's frame by the cycle's own alignment. It is counted per board: a
    board with two defects counts as found when either is hit.
  - The tool warped the mask with the engine's `warp_to`, which repeats the edge into the border; no VisA mask touches
    its image's edge (0 of 400), so that changed no count. The tool now uses a zero border.
  - A false call is a good board judged NG or WARN.
  - "AI check alone" counts the AI anomaly score check's own verdict, read from the same inspection.
- **Runs:** the per-run JSON files are in `/home/claude/runs/main/`, not in the repository. These runs were affected:
  - The first pass of set A was discarded after the tool's count of AI boxes was found reading the wrong source
    name.
  - A disk-full stop on the VM interrupted pcb3 and pcb4, which were run again from the start.
  - The VM's disk allowance raised AOI-LOG-005 (Drive nearly full) and AOI-LOG-006 (Drive full: OK evidence not kept)
    in some runs. Those alarms concern the VM, not the boards.

## A. VisA pcb1 to pcb4

- **Each run:** the good boards are shuffled with seed 0. The first 200 are the extra boards, never imported; the rest
  are the pool, from which each run imports its first n + 50, with all 100 anomalous boards.
- **Locked:** 50 good boards and 30 anomalous ones. Training saw n good boards, with 70 anomalous ones used only for
  calibration.
- **Held out:** 250 good boards (the 50 locked plus the 200 never imported) and the 30 locked anomalous ones.
- **Every run:** imports added every image, with none refused. The Validated freeze was refused (AOI-TRN-020). The
  shift check failed: its known-OK master was judged NG. To inspect at all, an Admin set `shift_check_hours` to 0.

| Run (category, good training images, input px) | Good: OK / WARN / NG | False calls | Defective: OK / WARN / NG | Missed | AI check alone: good flagged | AI check alone: defective passed | Defective with an AI box on its mask | Engine ms, median / p95 | Training s / peak MB |
|---|---|---|---|---|---|---|---|---|---|
| pcb1, 70, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 7 / 250 (≤ 5.2 %) | 14 / 30 (≤ 63.0 %) | 15 / 30 | 228 / 271 | 136 / 1571 |
| pcb1, 150, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 0 / 250 (≤ 1.2 %) | 29 / 30 (≤ 99.8 %) | 3 / 30 | 221 / 272 | 133 / 2726 |
| pcb1, 400, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 1 / 30 (≤ 14.9 %) | 0 / 250 (≤ 1.2 %) | 27 / 30 (≤ 97.2 %) | 4 / 30 | 215 / 249 | 190 / 3115 |
| pcb1, 150, **640** | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 0 / 250 (≤ 1.2 %) | 25 / 30 (≤ 93.2 %) | 6 / 30 | 257 / 291 | 1168 / 4066 |
| pcb2, 70, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 37 / 250 (≤ 19.0 %) | 5 / 30 (≤ 31.9 %) | 23 / 30 | 236 / 269 | 110 / 3285 |
| pcb2, 150, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 11 / 250 (≤ 7.2 %) | 11 / 30 (≤ 53.3 %) | 14 / 30 | 238 / 273 | 123 / 3603 |
| pcb2, 400, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 2 / 250 (≤ 2.5 %) | 12 / 30 (≤ 56.6 %) | 20 / 30 | 257 / 304 | 186 / 3985 |
| pcb3, 70, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 1 / 250 (≤ 1.9 %) | 21 / 30 (≤ 83.4 %) | 6 / 30 | 245 / 286 | 127 / 1554 |
| pcb3, 150, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 2 / 250 (≤ 2.5 %) | 19 / 30 (≤ 77.9 %) | 8 / 30 | 232 / 266 | 117 / 2363 |
| pcb3, 400, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 3 / 250 (≤ 3.1 %) | 23 / 30 (≤ 88.5 %) | 10 / 30 | 227 / 261 | 175 / 2875 |
| pcb4, 70, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 29 / 250 (≤ 15.5 %) | 1 / 30 (≤ 14.9 %) | 20 / 30 | 245 / 284 | 118 / 1556 |
| pcb4, 150, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 25 / 250 (≤ 13.7 %) | 0 / 30 (≤ 9.5 %) | 22 / 30 | 227 / 261 | 127 / 2796 |
| pcb4, 400, 256 | 0 / 0 / 250 | 250 / 250 (≤ 100 %) | 0 / 0 / 30 | 0 / 30 (≤ 9.5 %) | 6 / 250 (≤ 4.7 %) | 6 / 30 (≤ 35.7 %) | 16 / 30 | 238 / 276 | 178 / 3342 |

- **The miss in pcb1, 400:** that board was judged NG, but none of its defect boxes overlapped the mask.
- **Why every good board is NG (#453):** on pcb1's 150 OK run, the comparison's values on the 250 good boards had these
  medians, with the limit in brackets:
  - SSIM 0.467 (0.80)
  - Changed area 1.90 % (0.5 %)
  - Difference regions 92 (0)
  - Alignment inliers 364 (12)

  The inlier count suggests alignment works, and the difference is most likely ordinary photo-to-photo variation;
  the overlays were not inspected one by one. Learn From Labelled Boards (REQ-TRN-018) was not tried, because the
  test kept the default recipe, so a recipe cause is not ruled out.
- **The learning curve and the threshold (#454):** each threshold rule was "overlap: OK-based cut". The table gives
  the calibration NG images, of 70, that scored below the cut, by good training images:

  | Category | 70 | 150 | 400 |
  |---|---|---|---|
  | pcb1 | 43 | 68 | 63 |
  | pcb2 | 25 | 45 | 41 |
  | pcb3 | 61 | 52 | 61 |
  | pcb4 | 8 | 6 | 24 |

  In pcb1's 150 run, one calibration good image scored 17.6 against a median of 3.0, which set the threshold at 18.5.
- **256 against 640 px (ADR 0012), pcb1 at 150:**
  - The AI check passed 25 of 30 defective boards at 640 px, against 29 of 30 at 256 px, and flagged no good board at
    either.
  - The defect box landed on the mask for 6 boards against 3.
  - Training took 1,168 s at a 4.07 GB peak, against 133 s and 2.73 GB at 256 px.
  - The engine's time per board was 257 ms against 221 ms at the median.
  - On these counts 640 px buys little and costs nine times the training time.
- **Per defect type:** each anomalous board is given the type of its first VisA name: melt, burnt and damage are
  Damaged Component; dirt and extra are Contamination; wrong place is Misalignment. The table also counts all four
  categories' 150 OK runs; the other curve points are in the run files.

  | Type | Defective boards | Missed | AI check alone: passed | AI box on the mask |
  |---|---|---|---|---|
  | Bent Lead | 15 | 0 / 15 (≤ 18.1 %) | 7 / 15 (≤ 70.0 %) | 8 / 15 |
  | Contamination | 6 | 0 / 6 (≤ 39.3 %) | 0 / 6 (≤ 39.3 %) | 4 / 6 |
  | Damaged Component | 52 | 0 / 52 (≤ 5.6 %) | 31 / 52 (≤ 71.1 %) | 16 / 52 |
  | Misalignment | 3 | 0 / 3 (≤ 63.2 %) | 0 / 3 (≤ 63.2 %) | 3 / 3 |
  | Missing Component | 24 | 0 / 24 (≤ 11.7 %) | 12 / 24 (≤ 68.1 %) | 6 / 24 |
  | Scratch | 20 | 0 / 20 (≤ 13.9 %) | 9 / 20 (≤ 65.3 %) | 10 / 20 |

  Contamination and Misalignment come almost only from pcb4, where the AI check also flags many good boards. VisA's
  "extra" (an extra part) has no type of its own in the classification table.
- **Time, size and disk:**
  - The engine's time per board was 215 to 257 ms at the median and 249 to 304 ms at p95, against the 1 s target.
  - The wall time of one cycle, including the save, was 374 to 435 ms at the median.
  - Training at 256 px took 110 to 190 s, with a peak of 1.55 to 3.99 GB.
  - Every board was NG, so the evidence on disk is NG evidence only: 3.2 to 4.9 MB per board at the median (PNG plus
    maps). No good board was judged OK, so the OK figure could not be measured on photos (set E has it on drawn
    boards).
- **Result files, exports and AI Model Test:**
  - Each run wrote 280 result files, none invalid against the schema, each with its CSV, and the shift CSV.
  - AI Model Test on the locked set gave TP 30, FN 0 (≤ 9.5 %), FP 50 (of 50), TN 0 in every run. These are the
    combined verdict of both checks, not the AI check alone.
  - Export Report made `model_test_report.pdf`. Export CSV made its file. Export Image Overlays made 80 overlays.
  - Validation Report was refused in every run with AOI-TST-009, "No validation report from a Trial version": "No
    customer validation report was made: the run tested the locked validation set of DS-…, a Trial version that one
    person froze without a second person checking its labels or an agreement check."
- **Alarms met:**
  - AOI-INSP-003, Board judged NG.
  - AOI-INSP-016, Shift check needed.
  - AOI-LOG-005 and AOI-LOG-006, the VM's disk.
- **Where a non-technical user would be stuck:**
  1. The station calls every board NG. Nothing on screen says the comparison, not the board, is at fault.
  2. The failed shift check blocks Inspection. Only an Admin can turn it off on Settings, and nothing suggests that
     anything other than retraining will help.
  3. An Engineer cannot export the evidence of a validation run, because the exports need an Admin (Q58, by design).
  4. A Trial run cannot give a Validation Report (by design). A one-person shop cannot make a Validated version, which
     needs a second person.
  5. Training shows the threshold rule's text, "N/70 labelled NG below it", but does not say that this means the AI
     check will pass most defects.

## B. Photo changes, VisA pcb1

- **Setup:** the model is pcb1's 150 good, 256 px run from set A, trained on unaltered images. It judged the same 280
  held-out boards under each change, with the masks moved with the image.
- **Every change:** every good and every defective board was NG, as in set A. The informative counts are the AI
  check's own:

| Change | Image px | AI check alone: good flagged | AI check alone: defective passed | Good boards' AI score, median / p95 | Defective boards' AI score, median | Good boards' SSIM, median | Engine ms, median / p95 |
|---|---|---|---|---|---|---|---|
| none | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 29 / 30 | 2.65 / 5.21 | 5.60 | 0.467 | 233 / 284 |
| 5 MP | 2561 × 1952 | 5 / 250 (≤ 4.2 %) | 28 / 30 | 2.87 / 6.56 | 6.09 | 0.439 | 306 / 363 |
| JPEG 70 | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 28 / 30 | 2.68 / 5.48 | 6.02 | 0.449 | 224 / 267 |
| rotate +2° | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 29 / 30 | 2.63 / 5.55 | 5.54 | 0.500 | 209 / 249 |
| rotate −2° | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 28 / 30 | 2.73 / 5.17 | 5.49 | 0.497 | 217 / 256 |
| shift 20 px | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 28 / 30 | 2.80 / 5.56 | 5.92 | 0.471 | 209 / 240 |
| brightness +15 % | 1404 × 1070 | 1 / 250 (≤ 1.9 %) | 27 / 30 | 3.62 / 6.75 | 7.16 | 0.421 | 226 / 260 |
| brightness −15 % | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 29 / 30 | 4.87 / 5.96 | 6.15 | 0.516 | 211 / 240 |
| slight blur | 1404 × 1070 | 0 / 250 (≤ 1.2 %) | 29 / 30 | 2.40 / 4.38 | 5.04 | 0.596 | 214 / 247 |

- **Rotation −2°:** one defective board was NG, but its defect boxes missed the moved mask.
- **AI check counts:** this model's threshold (18.5, see #454) sits far above every score, so the check's verdicts
  hardly change. The scores show the sensitivity, and brightness is the change that moves good boards' scores.
- **Golden-board comparison:** it fails on unaltered photos, so its robustness cannot be judged here.
- **Errors and sources:** no AOI error was met, and the sources were unchanged.

## C. DeepPCB, rerun of 2026-10-08

- **Command:** `python tools/dataset_check.py --deeppcb <PCBData> --ai --out <outside>`, the 2026-10-08 arguments,
  with `OMP_NUM_THREADS=2` and `MKL_NUM_THREADS=2`.
- **Result:** identical to the 2026-10-08 record (`golden_same` and `ai_same` both true), so there is no finding.
  - Golden-board comparison: 500 of 500 defective boards NG (0 passed, ≤ 0.6 %); 324 of 3,140 boxes missed
    (≤ 11.3 %); 786 regions on no box.
  - Misses per type: open 176, mousebite 66, short 46, spur 27, copper 5, pin-hole 4.
  - AI model alone, held out: of 168 good boards, 1 NG and 9 WARN, so 10 false calls (≤ 9.9 %); of 168 defective
    boards, 115 OK (≤ 74.4 %) and 31 WARN.
- **Time:** golden-board comparison median 79.1 ms, p95 148.3 ms per board at 640 × 640 px. AI training median 176.5
  s per group, with a 1,171 MB peak.
- **Note:** the run took 1,282 s while a set A run shared the VM. Python was 3.13.18 here, against 3.11.15 then.

## D. PKU-Market-PCB: skipped

PKU-Market-PCB's pages state no licence. Legal & Compliance does not allow data with no licence stated. Its only
downloads are a Baidu Netdisk link (`https://pan.baidu.com/s/1hoPNd7_SAxOWa2XbBZZuTg`) and a torrent, so nothing was
downloaded. MVTec AD is excluded as non-commercial (CC BY-NC-SA 4.0).

## E. Control: the synthetic regression set and the demo bundle

These read no public data. They show what the same path does on boards the program was built around, which is where
the photos differ.

- **The synthetic regression set:** it went through `InspectionCycle` with its Golden board, no AI model and the shift
  check off, as the regression test runs it.
  - All 40 verdicts were the ones in `expected.json` (40 of 40).
  - Good boards: 20 OK, so 0 false calls (≤ 13.9 %). Defective boards: 13 NG and 7 OK, so 7 missed (≤ 55.8 %).
    The 7 OK ones are expected there: 3 Solder Bridge, 2 Solder Ball, 1 Contamination and 1 Misalignment, which the
    comparison alone does not catch at the default recipe.
  - The engine took 33.7 ms per board at the median and 44.2 ms at p95, at 640 × 480 px.
  - Evidence on disk: 176 KB per OK board and 505 KB per NG board, at the median.
- **The demo bundle,** as the build makes it:
  - AI Model Test on its locked set: TP 11, FN 0 (≤ 23.8 %), FP 3 (≤ 14.8 %), TN 47.
  - Its 10 scripted boards through `InspectionCycle`: 9 good boards OK (0 false calls, ≤ 28.3 %) and 1 defective
    board NG (0 missed, ≤ 95 %). Engine time was 55
    ms at the median. Evidence was 280 KB per OK board and 651 KB per NG board.
  - It wrote 10 result files, all valid, and the shift CSV.
  - Export Report, Export CSV and Export Image Overlays (61 files) were made. The Validation Report was refused with
    AOI-TST-007, because the demo stores no labeller agreement check.
- **Drawn boards, regression-style, through the whole path of set A:**
  - Imported: 120 good and 40 defective boards, 640 × 480, each defect boxed. Trial frozen, locked (50 good and 12
    defective), trained on 70 good boards in 103 s with a 1.40 GB peak, and activated.
  - The shift check passed on its four master samples.
  - Held out: 150 good boards (50 locked and 100 never imported) and 12 defective ones.
    - Good boards: 107 OK, 35 WARN and 8 NG, so 43 of 150 false calls (≤ 35.4 %).
    - Defective boards: 11 NG and 1 WARN, so 0 of 12 missed (≤ 22.1 %), and every defective board had an AI box on its
      mask.
  - Of the 43 false calls, 25 came from the AI check. The other 18 named no single check as WARN or NG in the record;
    they were not examined further.
  - The engine took 57 ms per board at the median. Evidence was 436 KB per OK board and 799 KB per NG board.
  - All 162 result files were valid. The exports were made, but the Validation Report was refused (AOI-TST-009, a
    Trial version).

The control shows the path works where the images match the Golden board closely: the shift check passes, good
boards come out OK, and verdicts follow the expected ones. That makes the photos the likely cause of the difference on
VisA, though the default recipe was not varied to rule it out.

## What could not run, and why

- **A Validated version:** a second person must check the NG labels (AOI-TRN-020). The Trial path was used, so no
  customer Validation Report could be made (AOI-TST-009).
- **PKU-Market-PCB:** it states no licence. MVTec AD is non-commercial.
- **The pinned CPU PyTorch wheel:** its index was blocked from the VM. The same version came from PyPI and ran on the
  CPU.
- **Learn From Labelled Boards and any other recipe:** not run, because the test kept the default recipe. It is the
  first thing to try for #453.
