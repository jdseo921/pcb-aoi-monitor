# Performance tests

Both checks time `Inspector.inspect` with the default recipe and no AI model over the synthetic regression set
(`tests/regression/`): all 40 boards at 0.3 MP (640 x 480) and all 40 scaled to 5 MP (2592 x 1944) by cubic resize,
after one untimed warm-up board per size.

**These are not the product's speed.** CI runners and developer machines are not the reference PC (plan item J4),
the boards are drawings, and the AI model is off. The figure that counts for REQ-INSP-007 comes from the
feasibility test on real boards on the reference PC (S30).

## The CI gate: base against head

A runner is another machine every time, so a stored baseline cannot judge it. The CI job "Performance (base vs
head)" (Linux) checks out the base commit beside the head (for a pull request its base and the merge commit CI tests;
for a push to main the commit before the push) and runs `tools/perf_compare.py`, which times both on that runner and
fails when the head's median or 95th percentile, at 0.3 MP or at 5 MP, is over 1.10 times the base's. Locally:

```
python tools/perf_compare.py --base <folder, or a git ref such as main> --head .
```

Exit codes: 0 within, 1 slower, 2 a usage error, 3 the trees cannot be compared. It writes `perf-compare.json`
(each board's time in each round, with the machine), which CI uploads. `test_perf_compare.py` proves the gate: exactly
1.10 times passes and 0.1 ms more fails, and the tool fails a tree that sleeps 50 ms per board (about 20 s).

A gate that fails unchanged code is as useless as one that never fails, and runners are noisy. So each tree runs in
its own process with only its own `aoi` imported, under one harness (the head's copy of the tool), on the same boards;
3 rounds per tree, a fresh process each, in the order base, head, head, base, base, head, each round with its own
board order, the same for both trees; each board keeps its fastest time over the rounds, and at 0.3 MP over 3 passes
per round, before the median and the 95th percentile are taken; and a failure is judged again over 6 rounds before it
counts. Noise only adds time and rarely hits one board every time; a real slowdown is there every time. Measured on a
shared cloud VM (Linux, 4 virtual CPUs, Intel Xeon at 2.10 GHz, other jobs running), not a runner:

- a 5 MP board takes 0.7 to 1.0 s instead of 0.45 s one time in five, at changing places, so one pass's 95th
  percentile measures that (687 to 1018 ms for unchanged code); a 0.3 MP pass lasts 1.5 s, so one burst moves it
  (unchanged code: 0.94 to 1.07 x with one pass per round, 0.97 to 1.03 x with three, five runs each);
- unchanged code, 5 runs: 0.88 to 1.04 x; 5 MP over 12 runs: 0.88 to 1.09 x after 3 rounds, 0.90 to 1.05 x after 6;
- 15 % slower (`inspect` sleeps 0.15 times its own time): 1.14 to 1.18 x everywhere; 50 ms slower per board: 2.65 to
  2.75 x at 0.3 MP, 1.12 to 1.14 x at 5 MP; both failed. A run takes 3 min, 6 to 7 min when it confirms a failure.

**A pull request that changes the Inspector API** so that the base cannot run the head's harness fails the job with
exit code 3, naming the tree and the error. No label or input skips it. Either the pull request teaches the harness
both APIs, which then shows in its diff, or its body explains the change with timings taken by hand, and Jay decides.

## The per-machine baseline

`test_timing.py` runs with the other tests. It writes `perf.json` (median and 95th percentile per size, with the
machine) and compares the medians with `baseline.json` for the same machine fingerprint (system, architecture, CPU
count and model): a median more than 10 % over fails. A machine with no entry, a CI runner among them, records only.
On every machine the 0.3 MP 95th percentile must stay under 1 s, the REQ-INSP-007 budget. It compares medians only:
a single pass's 95th percentile at 5 MP moves by a third with the noise above.

Record a baseline for a machine, after a change that is meant to be faster or when a new machine joins:

```
AOI_PERF_BASELINE=update pytest tests/perf
```

Commit the new `baseline.json` with the before and after numbers in the pull request, named by machine.
