# Training progress and time left, 2026-10-09

Stage S40 made training a job of the app that reports its progress (REQ-TRN-008): a training run reports its percent
and time left after every image read, every step of the Golden board's median, every training step and every
calibration map. The requirement asks that progress and time left update at least every 10 s, and that Cancel stop
the run within 10 s. This record measures, on a real run rather than the fake clock of `tests/test_training_job.py`,
how far apart the reports come and how close the time left is to the time the run then takes.

**Synthetic boards only.** These numbers describe time. They are not accuracy and are never quoted as accuracy.

## Set-up

- Code: branch feat/REQ-TRN-008-training-job (S40), through `AppContext.train` with a progress listener, as
  `start_training` runs it, from a frozen version in a customer's dataset store. It ran before the percent was kept
  from falling (below), which changes no time and no time left.
- Machine: the same cloud VM as the [training memory record](2026-10-09-training-memory.md), not the reference PC,
  which is still open: 4 virtual CPUs (Intel Xeon, 2.1 GHz), 16 GB of memory, no GPU; Python 3.11.15, PyTorch 2.14.1
  on the CPU, OpenCV 5.0.0, NumPy 2.4.6. Nothing else ran during each run.
- Boards and run: the memory record's, with a reports file: 50 OK and 3 NG PNG boards, 60 epochs at 256 px, the
  Golden board's band and step as shipped (`golden.BAND_BYTES`, 1 GiB; `golden.STEP_BYTES`, 64 MiB):

      python -m tests.training_memory_worker <folder> 5184 3888 50 3 0 60 256 .png <folder>/reports.json
      python -m tests.training_memory_worker <folder> 2592 1944 50 3 0 60 256 .png <folder>/reports.json

- A gap is the time from one report to the next, the first from the run's start and the last to its end. A report's
  error is the time left it gave less the time the run then took: positive when it said longer.

## Results

| Size | Run | Reports | Longest gap | Next longest | Time left at the 2nd report | Largest error | Median error |
|---|---|---|---|---|---|---|---|
| 20 MP (5184 × 3888) | 238 s | 701 | 4.14 s | 1.30 s | 247 s for 234 s | +53.5 s, aligning | 5.1 s |
| 5 MP (2592 × 1944) | 108 s | 565 | 3.54 s | 0.81 s | 100 s for 104 s | +9.5 s, first training step | 0.6 s |

Each kind of step at 20 MP, the mean and longest:

| Step | Count | Mean | Longest |
|---|---|---|---|
| An image read while aligning (read, decrypted, decoded, registered and warped) | 53 | 1.02 s | 1.30 s |
| An OK image read again for a later band (warped with the homography kept) | 100 | 0.64 s | 0.90 s |
| A step of a band's median (64 MiB of rows of 50 images) | 48 | 0.69 s | 0.76 s |
| A training step (a batch of 8 at 256 px) | 480 | 0.16 s | 0.31 s |
| A calibration map, made and scored | 15 | 0.26 s | 0.88 s, the first |

- **Gaps.** No two reports came more than 4.1 s apart at 20 MP or 3.5 s at 5 MP, under half the 10 s allowed. The
  longest is the first: it covers reading the reference board and timing a step of each other kind (the probes);
  every later gap is one step. Cancel is asked after every report, so it stops the run within the longest gap, at
  most 4.1 s here, and `tests/test_training_job.py` shows it on a fake clock in every phase.
- **Time left.** Known from the second report on, as the run timed one step of each kind on its first image, and
  never unknown after it. At 20 MP it erred long, never short by more than 0.7 s; the largest errors came while the
  images were aligned, up to 54 s too long (22 % of the run), 38 s of it because each later band's read, which
  registers nothing, took 0.64 s yet was counted at an aligning read's 1.02 s. At 5 MP, one band, it read 4 s short
  at the second report and within 3 s while aligning. At either size the first real training step, slower than the
  rest, put it up to 13 s too long for a moment; from epoch 3 on it came within 7 s, and the first calibration map
  did the same, up to 9 s. The median error was 5.1 s at 20 MP and 0.6 s at 5 MP.
- **Percent.** It never falls (`Eta.report`): on these runs it would have stepped back 1 to 4 points 8 times, as
  the first real training step and map took longer than timed.
- **Cost.** The runs took 238 s at 20 MP and 108 s at 5 MP, against 229 s and 104 s in S39 (the
  [training memory record](2026-10-09-training-memory.md)), and peaked at 2.51 GB and 1.88 GB of memory against 2.40 GB
  and 1.86 GB: the probes, the reports and run-to-run variation, well within the 10 min and 8 GB budgets.

## Where it led

Requirement row REQ-TRN-008 quotes this record. Counting a later band's read as a kind of its own would bring the
time left closer while the images are aligned; it is left for later, as the estimate errs long and settles once
training begins. The reference PC, once chosen, gets the same runs.
