# ADR 0017: Learning the comparison from a board model's labelled boards, and fine alignment

- Status: Proposed under Jay's instruction of 2026-10-11 ("Make it flawlessly function through stage 1 demonstration
  and usage of any training data to detect defects at proficient accuracy"; decisions follow industry norms). Jay's
  merge of this record accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-018 (now Done), REQ-RCP-007 (new, SHOULD G1), REQ-RCP-004, ADR 0016, `aoi/core/tuning.py`,
  `aoi/core/imaging.py` (`refine`), `AppContext.learn_comparison` (new), `Recipe.fine_alignment` (new),
  `aoi/ui/pages/recipe_learn.py`, AOI-RCP-013 (new)

## Context

The golden board comparison finds a defect where a board's colour differs from the Golden board's by the Pixel
difference or more over the Minimum defect area or more. Its defaults, 45 and 40 px, are one guess for every board.
On public bare-board scans they missed 9 to 10 % of the boxed defects, and the pair learned from labelled boards
missed under 2 % (docs/tests/2026-10-09-comparison-training.md, docs/tests/2026-10-10-deeppcb-tuning.md). Until now
only the public dataset check could learn the pair: an Engineer with a customer's labelled boards had no way to do it
in the app, and so no way to make "any training data" improve what the comparison finds.

On DeepPCB, 129 of 1,016 defect-free 512 px squares held a false call even at the learned pair
(docs/tests/2026-10-10-deeppcb-tuning.md). ORB's homography places a board to within a pixel or two, and the comparison
marks a copper edge it is off by as changed; refining the alignment to a fraction of a pixel, by the method below,
halved them as the app counts them (127 to 62 of about 1,013 windows on the test split, with 3,093 and 3,092 of 3,140
boxed defects found: docs/tests/2026-10-11-fine-alignment.md). AOI systems align on fiducials to a fraction of a pixel
for this reason.

## Decision

1. **Learn in the app, from the board model's own labels.** `AppContext.learn_comparison` (Engineer) takes the board
   model's samples in the Golden board's view labelled OK, and labelled NG with defect boxes (drawn, or imported with
   ADR 0016), the Golden board's own sample left out. Each board is aligned and compared as the Inspector does it, and
   counted at every pair of Pixel difference and Minimum defect area tried, with fine alignment off and on. Its boxes
   are mapped onto the Golden board through the board's own homography, so a board that lies off still counts right.
2. **Choose on some boards, count on others.** Boards a locked validation set holds (by SHA-256) are only counted on,
   never chosen on, as that set exists to be judged once. When it holds fewer than one NG board, or leaves fewer than
   two to choose on, a third of the OK and of the NG boards is held out with a recorded seed instead. At least three
   NG images with boxes are needed (AOI-RCP-013).
3. **The rule REQ-TRN-018 set, made steady.** The setting chosen has the fewest false calls among those that miss at
   most 1 % of the boxed defects; then the fewest missed; then fine alignment off, which is faster. On a few boards
   many settings tie with nothing missed and nothing false, and the highest of them, which the dataset check took,
   sits a step from missing a defect: on six boards it missed one of two held out. Of settings that tie, the one
   deepest among them (furthest, in steps of the values tried, from any setting that does worse) is chosen, so a board
   a little unlike the ones counted is judged alike.
4. **Counts, never a promise.** The sheet shows the chosen setting beside the recipe's own on the held-out boards:
   missed defects, false calls per 512 px square that holds no boxed defect, and OK boards called NG, each a count
   over its 95 % upper bound (Customers & Launch, "Claims carry counts").
5. **Nothing is stored by learning.** Use Learned Values fills the fields; Save Recipe stores them as a revision after
   its before → after list, with the counts offered as the reason, so the audit entry carries the evidence
   (REQ-RCP-004). A recipe decides verdicts, so an Engineer always sees and confirms the change.
6. **Fine alignment is a recipe setting, off by default.** With it on, ORB's homography is refined by maximising the
   correlation of the two boards' grey levels (OpenCV's ECC) on the boards scaled to at most 1,024 px, and taken only
   when the correlation rises and no corner of the board moves more than 8 px; otherwise ORB's stays. The alignment
   method then reads "orb-homography+fine". The recipe stores the setting only while it is on, so every recipe saved
   before reads, compares and audits exactly as it did.

## Consequences

- No verdict changes on upgrade: fine alignment is off and not stored unless an Engineer turns it on, learning stores
  nothing, and the synthetic regression set's verdicts and metrics are unchanged. A recipe saved with learned values
  or fine alignment changes verdicts for its board model, as any recipe revision does, and is audited as one.
- Fine alignment costs about 0.1 s per board (docs/tests/2026-10-11-fine-alignment.md), within REQ-INSP-007's 1 s at
  the sizes measured; CI's performance gate times the default recipe, so it does not see that cost.
- The service API grows: `learn_comparison(board_model, progress, should_stop, seed)` returns the chosen and current
  settings, the boards each part held, why any board was left out, and each setting's rates on the held-out boards.
  `tuning.board_tables`, `map_boxes` and `choose_setting` are new; `choose` keeps its signature and now breaks ties as
  `choose_setting` does, so the public dataset check may choose a different pair where pairs tie.
- Learning reads every labelled board twice at full size, on the pool, with progress and Cancel: about a second a
  board at 5 MP on the cloud VM measured.
- Not done: learning the similarity minimum, the changed-area limit and the AI score threshold, which the comparison's
  counts do not bear on; learning per ROI; and a written record of a learning run that is not saved.
