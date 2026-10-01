# Synthetic regression set

Twenty OK and twenty NG boards, drawn by `make_regression_set.py` from a fixed seed, and in `expected.json`
the verdict and metrics the golden-sample compare step gave each one when the file was last baselined.
`test_regression_verdicts.py` regenerates the boards on every run and checks that every verdict is unchanged
and every metric is within the tolerances recorded in the file. Neither the images nor their hashes are
committed: PNG bytes differ between OpenCV and zlib builds, verdicts and metrics do not.

**It is never accuracy.** The boards are drawings of one board model with seven defect types painted on; a
result on them says that the code still behaves as it did, not how it will do on a customer's boards
(Customers & Launch standard, "Validation and accuracy claims"). Real-board figures come from the feasibility
test on photographs (stage S30, issue #10).

## What the baseline holds

The default recipe (no AI model, `diff_threshold` 45, `min_defect_area` 40 px) on 640 x 480 drawings:

| Boards | Expected | Why |
|---|---|---|
| 20 OK | OK, no difference region | Capture jitter (±6 px, ±1°, lighting, noise) stays under the thresholds |
| 13 NG | NG, a region on the painted defect | Missing part, polarity mark, scratch, large shift, large contamination spot |
| 7 NG | OK, no region (`"found": false`) | A 5 x 7 px solder bridge, three 3 px solder balls, a 10 px shift of a 34 x 14 px resistor and one 21 x 19 px contamination spot are below the default sensitivity at this resolution (see `docs/tests/2026-10-01-resolution-test.md`) |

The seven misses are kept on purpose: a change that starts catching them, or stops catching the other
thirteen, is a change that alters verdicts and must be seen in review.

## Re-baselining

Only when a change is meant to alter verdicts (Engineering standard, "Change control"):

1. `python tests/regression/make_regression_set.py --write-expected`
2. Put the before/after counts (NG found, OK boards flagged) in the "Changes that can alter verdicts" section
   of `docs/release-notes/unreleased.md`.
3. Say in the pull request which boards changed and why; Jay approves the new baseline by merging.

`--out <folder>` also writes the boards and a `manifest.json` (label, defect type, defect box) so the images
can be looked at.
