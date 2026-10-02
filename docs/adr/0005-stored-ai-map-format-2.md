# ADR 0005: Stored AI map format 2

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-02
- Decides: the product owner (Jay), until a tech lead joins
- Related: stage S28a of the Stage 1 plan; REQ-CMP-005, REQ-INSP-012; Engineering standard "Data and storage";
  `aoi/core/maps.py`; [ADR 0004](0004-schema-v1.md) (records and writes)

## Context

Since S25c each result's AI score map is stored beside its overlay as a 16-bit PNG, `<base>_ai.png`, holding the score
in 0.001 σ steps clipped at 65.535 σ (format 1). REQ-CMP-005 judges a stored result again from its maps without the AI
model, and format 1 gets two things wrong there. A pixel above 65.535 σ reads back lower, so a higher AI threshold
judges it otherwise; a model this app trains can score up to 1000 σ (`anomaly.SPREAD_FLOOR`). And rounding to the
nearest step can take a pixel across the AI model's pixel threshold, so the AI defect found again is a pixel wider or
narrower than the one judged, and an ROI peak just under its threshold can read as on it.

## Decision

1. **Format 2**, `<base>_ai2.png`, 16-bit: a code below 32768 is code / 1000 σ (0.001 σ steps up to 32.767 σ, as
   before); a code c from 32768 up is 32.768 · e^((c − 32768) / 8192) σ, each step 1/8192 of the value, up to
   1788.85 σ. NaN and values below 0 store as 0, values from the top up as the top code. Reading is one table lookup.
2. **The pixel threshold's side is kept.** The encoder takes the AI model's pixel threshold and moves a pixel the
   rounding took across it back one code, so the stored map marks the AI defect pixels the live one did, each value
   still within one step.
3. **An ROI keeps the peak it was judged by.** Judging again takes an ROI's peak from its stored check (its value
   times the AI threshold, exact in float32), not from the map; an ROI added, moved or renamed since reads the map.
4. **Formats are told apart by file name.** Format 1 files keep their name and read as before; a later format takes
   a new name and decoder beside the old, so no record or migration changes.
5. **Unreadable maps say so.** A map file that is gone reads as missing (AOI-CMP-001 once both are); one that is there
   but cannot be read or decoded raises AOI-CMP-003, naming the file and why.

## Alternatives considered

- **32-bit float TIFF.** Exact, but twice the raw bytes (20 MB against 10 MB at 5 MP before compression), float noise
  compresses poorly, and float TIFF support differs between OpenCV builds.
- **One linear 16-bit scale with a larger step** (0.01 σ to 655 σ). Ten times coarser at the 1 to 5 σ where pixel
  and image thresholds lie.
- **The threshold side in a second file.** One more file per result to keep in step with the map and the sweep.
- **Running the AI model again.** REQ-CMP-005 asks for no model run, within 300 ms at 5 MP.

## Consequences

- A result stored from S28a on is judged again as the live one would be, except an AI defect's score and an ROI added,
  moved or renamed since, each within one step over the AI threshold (`tests/test_re_evaluate.py`).
- A result stored between S25c and S27 is judged again with format 1's limits. Stage 1 has no customer stations yet,
  so none hold such files outside test workspaces.
