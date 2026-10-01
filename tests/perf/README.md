# Performance tests

`test_timing.py` times `Inspector.inspect` with the default recipe and no AI model over the synthetic regression
set (`tests/regression/`): all 40 boards at 0.3 MP (640 x 480) and 8 of them scaled to 5 MP (2592 x 1944). It
writes `perf.json` (median and 95th percentile per size, with the machine) and compares the medians with
`baseline.json` for the same machine fingerprint (system, architecture, CPU count and model). A median more than
10 % over the baseline fails. On a machine with no entry the numbers are recorded only, and on every machine the
0.3 MP 95th percentile must stay under 1 s, the REQ-INSP-007 budget.

**These are not the product's speed.** CI runners and developer machines are not the reference PC (plan item J4),
the boards are drawings, and the AI model is off. The figure that counts for REQ-INSP-007 comes from the
feasibility test on real boards on the reference PC (S30).

Record a baseline for a machine, after a change that is meant to be faster or when a new machine joins:

```
AOI_PERF_BASELINE=update pytest tests/perf
```

Commit the new `baseline.json` with the before and after numbers in the pull request, named by machine.
