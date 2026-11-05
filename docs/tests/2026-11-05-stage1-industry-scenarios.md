# Stage 1 industry-scenario tests on public data, 2026-11-05

Issue #459 (REQ-TST-008, test only, phase 2 of #452). Phase 1 asked whether Stage 1 runs end to end on real photos.
This phase asks whether a factory could use it: eleven scenarios a line meets, each run on a station **as shipped**
(the defaults) and on one **as commissioned** (day one done with only the app's own features).
`tools/proxy_scenarios.py` drove every run. Nothing under `aoi/` changed, and `tests/regression/expected.json` is
byte-identical to `b5bf413`.

**Jay's approval, verbatim:** "Jay approved on 2026-11-04 the use of the public datasets named in this record for
internal Stage 1 testing only. No image, box, mask or trained model from them enters the repository or ships, and no
result from them is quoted as accuracy." Jay's request of 2026-11-05 says this approval covers phase 2.

Every number below is a count from an internal test on someone else's boards, never an accuracy claim. Each bound is
the one-sided 95 % Clopper-Pearson upper bound (`upper_95` in `tools/dataset_check.py`). Where boards repeat (a
2,000-board shift drawn from 250 good and 30 defective boards), the bound quoted is over **distinct** boards; the
per-arrival bound would claim more evidence than there is.

## Summary

- **As shipped, could a factory use this to replace inspectors?** No. On VisA pcb1 to pcb4 it flagged 1,000 of 1,000
  held-out good boards (upper bound on the OK share 0.3 %), so the line would re-check every board, 360 an hour at one
  board every 10 s, and first-pass yield is 0. It also stops before the first board: the shift check fails on its
  known-OK master sample (#453). Being NG on every defective board says nothing when every board is NG.
- **As commissioned, could it?** No, though for a different reason. Commissioning fixed most of the comparison's
  limits; graded again from the stored checks, 864 of 1,000 good boards pass every check. But the engine makes any
  board with a difference region that is not Minor WARN (REQ-INSP-015, `aoi/core/inspector.py` step 5), so 0 of
  1,000 were OK (941 WARN, 59 NG). The shift check still fails, now with its OK master sample WARN.
- **Which scenarios fail, and why?**

  | Scenario | Shipped | Commissioned |
  |---|---|---|
  | S1 production mix | Fails: every good board NG | Fails: every good board WARN or NG (the region rule) |
  | S2 slow drift | Fails: 0 drift alarms with every board NG | Fails: 1 alarm, at board 1,544; no OK board to watch |
  | S3 placement | Holds: no backwards board OK, 0 alignment failures | Holds, the same |
  | S4 bad images | Holds: none OK; but an empty conveyor is stored as an NG board | Holds; blur is WARN only through the region rule |
  | S5 legitimate variation | Fails: 250 of 250 flagged | Fails: 250 of 250 flagged; no don't-care regions |
  | S6 few NG samples | The threshold never moves (18.50) | The threshold never moves (17.69); 3 NG gave 2 good OK |
  | S7 repeatability | Holds: 0 of 60 boards flip | 3 of 30 good and 11 of 30 defective flip NG/WARN |
  | S8 changeover | Holds: wrong model never OK; 1,256 s to a new model | Holds; 499 s; 24 actions on 4 screens either way |
  | S9 line rate | Keeps up; one record and file each; 1.5 GB of evidence an hour, an alert a board | Keeps up; the same disk use; the burst queues up to 2 s |
  | S10 faults | Result files lost for an outage (#465); orphaned evidence after a kill (#466) | A board stored twice after a kill (#466) |
  | S11 review loop | False calls do not fall; the gate accepts a worse model | The same |

- **Are #453 and #454 in the defaults or in the engine?** Both lie in the engine.
  - #453: commissioning, with the app's own tools, moves the comparison's checks to OK on most good boards, but the
    engine's region rule keeps every good board flagged and the shift check failing. The defaults make it worse, not
    different.
  - #454: the calibrated threshold stays at 18.50 shipped and 17.69 commissioned for 0, 3, 10 or 30 NG calibration
    boards (S6). The only way round it is to type another threshold into the recipe, from scores no screen shows.
- **The three code changes that would do most, ranked by expected effect:**
  1. **#460:** judge each difference region against good-board variation, behind an image-quality gate, instead of
     "any non-Minor region is WARN". The regrade shows it is the step between 0 and 864 of 1,000 good boards OK on a
     commissioned station; alone it would pass 20 of 120 defective boards, hence per-region tolerance and the gate.
  2. **#461:** a statistical Golden board (per-pixel mean and tolerance from many good boards) instead of one image.
     A good board's SSIM against the chosen Golden board is 0.47 at the median on pcb1, below an empty conveyor's 0.54.
  3. **#462:** the AI threshold from the held-out scores, shown with what it passes and flags. The calibrated one
     passed 29 of 30 defective pcb1 boards on the AI check alone; the best cut flagged 63 of 250 good pcb2 boards.
- **More data:** none usable was found (see Set-up), so every scenario ran on VisA only.

Issues opened: #460, #461 and #462 (ranked changes); #463 (a frame with no board is judged), #464 (the drift monitor
stays silent), #465 (result files lost while the output folder is unwritable), #466 (after an unclean stop), #467 (a
copied workspace opens the original) as defects; #468 (commissioning steps the app lacks, for Jay: feature freeze).
Evidence was added to #453 and #454.

## Set-up

- **Data:** VisA pcb1 to pcb4, CC BY 4.0, as in #452 (the download, its hash and the credit are in
  `2026-11-04-stage1-proxy-validation.md`). Each board model imports 200 good and 100 defective photos with their
  boxes; 250 good and 30 defective boards are held out and never imported. Variants are made in memory or in a folder
  outside the repository, from seed 0.
- **More data, licences checked before any download (2026-11-05):**
  - FICS-PCB (`eprint.iacr.org/2020/366`): the paper is CC BY, but no dataset licence or download was found, and the
    host lets only verified users download. Not used.
  - FPIC (`physicaldb.ece.ufl.edu/?p=370`): assembled boards, but no licence stated and no defect labels. Not used.
  - Innodisk PCB (Hugging Face): CC BY-NC 4.0, non-commercial. Not used.
  - Mendeley PCB-Defect (`vdj74sngvn`): CC BY 4.0, but 230 bare etched boards, every one defective. Not used.
  - Dataset Ninja PCB Defect: licence unknown; bare boards with defects added by hand. Not used.
- **Machine:** Linux, 4 CPU cores, 15 GB RAM, no GPU (PyTorch 2.14.1 on CPU), Python 3.13. Up to two scenarios ran at
  once, so wall-clock times are under load; S9 records the load average beside each time.
- **The station as shipped:** the first-run guide's path with the defaults: import, Train AI (the guide's one press),
  Golden board as the guide sets it, the default recipe, the calibrated AI threshold.
- **The station as commissioned:** the shipped station, then the day-one steps an applications engineer would take,
  each as a screen and a call (`tools/proxy_station.py`, `commission`):

  | Step | Screen › action | pcb1 result |
  |---|---|---|
  | Golden board chosen | Training › samples › Set as Golden board | the most typical good board (0146.JPG), not the first imported |
  | Learn From Labelled Boards | Recipe Editor › Learn From Labelled Boards… › Use Learned Values | pixel 30, area 20, fine alignment on; but the chosen pair still called 50 of 50 held-out OK boards NG |
  | Whole-board limits | Recipe Editor › Thresholds, read off Compare for 60 commissioning boards | SSIM ≥ 0.23, changed area ≤ 10.8 %, regions ≤ 491 |
  | AI threshold | Recipe Editor › Thresholds › AI threshold override | best cut 5.29 of the calibration scores, set as 6.61, so that its WARN band (from 0.8 of it) starts at the cut; 17.69 calibrated |
  | Don't-care regions | **missing:** no ROI type excludes an area | none |
  | Inspection ROIs | none drawn: on VisA the whole board matters, and an ROI adds only a regional AI check | none |
  | Master samples | **missing:** the shift check takes the oldest OK and NG samples | none chosen |

  The best cut is the threshold with the highest Youden J on the calibration scores, computed by the tool from the
  model's registry row, since no screen shows those scores (#468). Each board model's steps are in its JSON.
- **The shift check** fails on both stations in every category, so an Admin turned it off (hours 0) for every
  scenario, as in #452; each run records the check's rows first.
- **Counts:** an *escape* is a defective board judged OK, or flagged with no flagged region on its defect's mask
  (warped to the Golden board); a *false call* is a good board judged WARN or NG; a refused board counts as a re-check.
- **The regrade** (`tools/proxy_regrade.py`): each stored board graded again from its stored checks alone, without the
  region rule. It is a what-if on stored values, to estimate what #460 could do, and never a verdict the app gave.

## S1 Production mix

A 2,000-board shift in arrival order at 1 % defective (20 boards) and at 0.2 % (4), drawn from the held-out boards,
each pool used up before a board comes again; a third run judged the 1 % shift board by board through
`InspectionCycle`. The four board models' held-out boards, judged once each:

| VisA | Good OK / WARN / NG, shipped | commissioned | Defective OK / WARN / NG, shipped | commissioned |
|---|---|---|---|---|
| pcb1 | 0 / 0 / 250 | 0 / 246 / 4 | 0 / 0 / 30 | 0 / 16 / 14 |
| pcb2 | 0 / 0 / 250 | 0 / 219 / 31 | 0 / 0 / 30 | 0 / 3 / 27 |
| pcb3 | 0 / 0 / 250 | 0 / 237 / 13 | 0 / 0 / 30 | 0 / 11 / 19 |
| pcb4 | 0 / 0 / 250 | 0 / 239 / 11 | 0 / 0 / 30 | 0 / 5 / 25 |

In the line's terms, the 1 % shift on pcb1, both configurations: 0 escapes of 20 defective arrivals (distinct boards:
0 of 20, upper 13.9 %), 1,980 false calls of 1,980 good arrivals (distinct: 250 of 250), first-pass yield 0, and 360
re-checks an hour at one board every 10 s. The 0.2 % shift is the same with 4 defective (upper 52.7 %). On pcb4 as
commissioned, 1 of 20 defective arrivals escaped (distinct upper 21.6 %). pcb2 and pcb3 gave the same line counts as
pcb1. The board-by-board run gave the same verdict as the batch run on 2,000 of 2,000 arrivals. 1,730 arrivals reuse
a board already seen.

Regrade, commissioned (what-if): 234, 183, 221 and 226 of 250 good boards would be OK on the checks alone, and 12, 1,
6 and 1 of 30 defective boards would pass. Where the commissioned good boards are NG, the AI check is the cause in
3 of 4 (pcb1), 27 of 31 (pcb2), 9 of 13 (pcb3) and 10 of 11 (pcb4).

## S2 A shift's slow drift

The 1 % pcb1 shift again, while the camera drifts in smooth ramps to its worst at board 2,000: light 10 % down, colour
5 % warmer, 15 px creep, 0.5°, focus to a blur of σ 1 px.

- **False calls start** at board 0 in both: every good board was already flagged, so drift cannot add any.
- **The drift monitor (REQ-INSP-019):** shipped, 0 alarms in 2,000 boards. Commissioned, 1 alarm, at board 1,544
  ("10 of the last 50 boards called NG; 5.4 % of the 500 before"), from 97 NG among 1,980 good boards; the WARN rate
  never alarmed at 1,883 of 1,980, and the OK-score measure had no OK board to watch (#464).
- **The shift check** at board 0 (the 12 h check, at the start) and at board 1,440 (4 h at 10 s) failed on both
  stations, as it fails before any drift. It judges stored files (ADR 0014), so it could not see camera drift anyway.
- Regrade, commissioned: 1,821 of 1,980 good arrivals OK on the checks alone, 12 of 20 defective arrivals passing.

## S3 Board placement

277 boards (247 good, 30 defective) placed up to ±5° and ±60 px, and 33 more loaded backwards (180°).

| | Placed, shipped | Placed, commissioned | Backwards, shipped | Backwards, commissioned |
|---|---|---|---|---|
| Good boards | 247 NG | 244 WARN, 3 NG | 23 NG | 23 WARN |
| Defective boards | 30 NG | 15 WARN, 15 NG | 10 NG | 4 WARN, 6 NG |
| Alignment failures / OK | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Inliers (min to max) | 176 to 282 | 161 to 281 | 258 to 287 | 262 to 297 |

No backwards board was OK. The alignment's homography turns a backwards board round, so it is judged like a placed
one and nothing says it was turned; whether a backwards board should be refused instead is the line's decision.
1 of 30 placed defective boards was an escape in both (flagged, but not on its defect; upper 14.9 %).

## S4 Bad images, fail-safe

Five of each case, mixed into a pcb1 run. **No case came out OK in either configuration.**

| Case | Shipped | Commissioned |
|---|---|---|
| Over- and underexposed, hand over the board, empty conveyor, much smaller image, pcb2 shown to pcb1 | NG | NG |
| Motion blur | NG | 4 WARN, 1 NG |
| Out of focus | NG | 5 WARN |
| Duplicate file, 16-bit TIFF, CMYK JPEG, EXIF rotation | NG | WARN (valid photos of a good board) |
| Truncated file | refused, AOI-INSP-006 | refused, AOI-INSP-006 |
| Zero-byte file | refused, AOI-INSP-004 | refused, AOI-INSP-004 |

The empty conveyor and the much smaller image had 0 inliers, yet were judged and stored as NG boards with their
defects (#463). On the empty conveyor the commissioned station's SSIM (0.54) and AI checks passed; only changed area
(90.8 %) made it NG. The blurred frames were WARN only through the region rule: their stored checks are all OK, so
#460 needs the image-quality gate first.

## S5 Legitimate variation

50 good pcb1 boards per kind, each changed at a seeded place: a serial label, a component of another colour, a lot
code, solder sheen (local brightness), and unchanged.

| Kind | Shipped | Commissioned |
|---|---|---|
| Unchanged | 50 NG | 50 WARN |
| Serial label | 50 NG | 50 NG |
| Component colour | 50 NG | 37 WARN, 13 NG |
| Lot code | 50 NG | 27 WARN, 23 NG |
| Solder sheen | 50 NG | 50 WARN |

Every board of every kind was a false call (upper on the OK share 5.8 % per kind). As commissioned these must stay OK;
they cannot, since even the unchanged boards are WARN, and a label or lot code cannot be left out without
don't-care regions (#468). Regrade: 156 of 250 would be OK on the checks alone; the label and lot code stay NG.

## S6 Few defect samples

pcb1 calibrated with 0, 3, 10 and 30 NG boards (5, 15 and 43 imported, so that 3, 10 and 30 land in calibration);
200 good and 30 defective held-out boards judged each time.

| NG in calibration | Threshold, shipped / commissioned | Learned pair (pixel, area) | AI cut set | Good OK / WARN / NG, commissioned | Escapes, commissioned |
|---|---|---|---|---|---|
| 0 | 18.50 / 17.69 | refused, AOI-RCP-013 (needs 3) | none (no NG scores) | 0 / 194 / 6 | 0 of 30 |
| 3 | 18.50 / 17.69 | 70, 160 | 6.93 | 2 / 187 / 11 | 1 of 30 |
| 10 | 18.50 / 17.69 | 70, 20 | 7.35 | 0 / 197 / 3 | 1 of 30 |
| 30 | 18.50 / 17.69 | 45, 20 | 3.93 | 0 / 183 / 17 | 0 of 30 |

Shipped, every board was NG at every count. The calibrated threshold does not move with the NG boards (#454), and
Learn From Labelled Boards picks a different pair at each count (#461). The upper bound on escapes is 9.5 % at 0 of
30 and 14.9 % at 1 of 30.

## S7 Repeatability

30 good and 30 defective pcb1 boards, each shot 10 times (sub-pixel shift, sensor noise σ 2, light ±3 %). A board
flips when its 10 verdicts are not all the same.

| | Shipped | Commissioned |
|---|---|---|
| Good boards that flip | 0 of 30 (upper 9.5 %), all NG | 3 of 30 (upper 23.9 %), between WARN and NG |
| Defective boards that flip | 0 of 30 (upper 9.5 %), all NG | 11 of 30 (upper 53.3 %), between WARN and NG |

No shot of any board was OK, so no flip crossed between pass and fail; but a gauge study would not accept a verdict
that changes between shots of the same board, and 14 of 60 commissioned boards did.

## S8 New product and changeover

Mid-shift the line changes from pcb1 to pcb2 and back; then a pcb1 revision (a part added at a fixed place) arrives as
a new board model with 70 good images.

| Step | Shipped | Commissioned |
|---|---|---|
| pcb2 boards with PCB1 selected by mistake | 20 good, 10 defective: all NG | all NG |
| Changed over to PCB2 | all NG | good 19 WARN, 1 NG; defective 4 WARN, 6 NG |
| Changed back to PCB1 | all NG | good 20 WARN; defective 4 WARN, 6 NG |
| Revision boards with PCB1 selected | all NG | all NG |
| Changed over to PCB1R2 (50 good, 30 defective) | all NG | good 50 WARN; defective 24 WARN, 6 NG |
| PCB1 boards with PCB1R2 selected by mistake | all NG | good 20 WARN; defective 8 WARN, 2 NG |
| Time from first image to a working PCB2 / PCB1R2 | 1,256 s / 826 s | 499 s / 293 s |
| Actions | 24 on 4 screens (the guide's path, `tests/test_guide_click_count.py`) plus the commissioning steps |
| First verdict after a changeover | 0.6 to 1.2 s | 0.6 to 1.9 s |

The wrong board model was never OK. Most of each time is training on CPU, and the two runs were under different load,
so the times are not a comparison of the configurations. A wrong model is caught only because every board is flagged;
the station does not say "this is not a PCB1".

## S9 Line rate and endurance

4 h of pcb1 boards at one every 10 s (1,440), then a burst of 100 at one every 2 s, through `InspectionCycle` with the
result files on, the two configurations at once on the 4-core machine (load average 1.7 to 5.7 over the run).

| | Shipped | Commissioned |
|---|---|---|
| Verdicts | 1,540 NG | 1,508 WARN, 32 NG |
| Time per board with the save, p50 / p95 / max | 1.41 / 2.70 / 3.66 s | 2.22 / 3.61 / 4.51 s |
| Of it the engine, p50 / p95 | 1.18 / 2.37 s | 1.92 / 3.32 s |
| Burst, p50 / p95 / max | 1.25 / 1.42 / 1.50 s | 1.90 / 2.54 / 2.89 s |
| Backlog at 10 s / in the burst | none / none | none / 75 of 100 boards waited, at most 1.97 s, 0.40 s at the end |
| Memory (RSS) | 529 MB at start, 692 MB after an hour, then +7 MB per 360 boards | 530, 730, then +0.4 MB per 360 |
| Workspace growth per 360 boards (an hour) | 1,544 MB | 1,521 MB |
| Result files per 360 boards | 4.9 MB | 12.7 MB |
| One record, one JSON, one CSV and one shift-file row per board | 1,540 of 1,540, none twice, none without a record | the same |
| Alerts (`logs/alerts.jsonl`) | AOI-INSP-003 for each of 1,540 NG boards; AOI-LOG-006 once | AOI-INSP-003 32; AOI-LOG-006 once |

- **Time:** both stations kept up with the line at 10 s, but no board met the 1 s verdict budget (REQ-INSP-007) on
  this loaded CPU. That is a fact about this machine under load, not about the station's PC; it is not a budget test.
- **Disk is the limit.** With every board flagged, each keeps its full evidence: about 1.5 GB an hour, 6.6 GB in
  4.1 h, so a 24-hour line fills about 37 GB a day. Both stations raised AOI-LOG-006 when the drive (shared with the
  other runs) crossed 95 %. Retention had not been confirmed by an Admin, so its sweep at the end removed nothing; with
  no OK board there were no OK maps to remove anyway. Fixing the false calls (#460) is what makes the disk last.
- **Heartbeat:** written every minute to the end; its last hour counted 432 boards (431 commissioned) and 0 false
  calls, as no one reviewed. Its `ng` counts NG only (13 commissioned), so a station that flags every board WARN looks
  healthy there.
- **Alerts:** shipped, one NG alert a board, 1,540 in 4.1 h: an alarm list an operator would stop reading.

## S10 Faults during production

Run on its own pcb1 station rather than during S9, so that S9's times stay clean (a deviation from the request).

- **Disk at 95 %** (the app's usage patched, as its tests do), 40 good and 10 defective boards: every board had one
  record, one JSON and one CSV; every flagged board kept its overlay. Shipped raised AOI-LOG-006. Commissioned raised
  none, because the real drive had crossed 95 % a minute before (the runs were filling it) and that alarm
  had already been raised; both behaved as the drive's state says.
- **Output folder unwritable** for 25 boards (`chattr +i`): 25 records saved, **0 result files written**, one alarm
  (AOI-INSP-019) naming the first board, and the 25 files never written once the folder was writable (#465). Before
  and after, 10 of 10 each.
- **Killed mid-save** (SIGKILL 0, 0.05 and 0.2 s into a board), then restarted from the board in hand, 30 boards:

  | | Records | Lost | Stored twice | Evidence with no record | Open / first verdict after restart |
  |---|---|---|---|---|---|
  | Shipped | 30 | 0 | 0 | 2 files of one board | 1.7 s / 3.1 to 3.3 s |
  | Commissioned | 31 | 0 | 1 (the 0.2 s kill) | 0 | 1.4 to 1.8 s / 2.9 to 4.1 s |

  The operator is not told which board was saved last, so re-presenting the board in hand stores it twice when it
  had been saved (#466). The heartbeat's unclean-start marker is only logged.

## S11 The operator's review loop

A shift of 100 good boards never imported and 15 defective ones, every NG and WARN reviewed by its mask (100 False
call, 15 Real defect); the 100 false calls added to Training as good; a new Trial version trained and activated; then a
second one with 5 real defects wrongly added as good, as a hurried review does. Each judged on 100 more good and the
other 15 defective boards.

| Version | Locked-set AI Model Test | False calls | Escapes, shipped | Escapes, commissioned |
|---|---|---|---|---|
| v1.0 (before) | TP 30, FN 0, FP 50, TN 0 | 100 of 100 | 0 of 15 | 0 of 15 |
| v1.1 (+100 false calls as good) | the same | 100 of 100 | 0 of 15 | 1 of 15 (upper 27.9 %) |
| v1.2 (+5 defects as good) | the same | 100 of 100 | 1 of 15 (upper 27.9 %) | 1 of 15 |

False calls did not fall, since the comparison and the region rule flag every good board whatever the AI model learns.
Both new versions were activated: the go-live gate's comparison with the live version is not built yet (REQ-TRN-012,
Partial, release 1.0), and the AI Model Test cannot tell the versions apart when every good board is NG.

## Reproduce

On `test/459-record` (the tool is complete at the top of the stack), with VisA extracted outside the repository:

```
python -m tools.proxy_scenarios --scenario S1 --config commissioned --data <VisA root> --out <folder> --seed 0
python tools/proxy_regrade.py <folder>/runs/S1-commissioned-pcb1-baseline
```

`--scenario` takes S1 to S11 (S9 and S10 on Linux only), `--config` shipped or commissioned, `--categories` pcb1 by
default (S1 ran with `pcb1,pcb2,pcb3,pcb4`). Each run writes `<S>-<config>.json` and its stations under `runs/`; it
exits 1 only when a step reports an error.
