# 2026-10 business readiness: progress

**This file was not in the repository** when Jay's message of 2026-10-12 12:53 UTC asked for it to be read, and
neither was `docs/plans/2026-10-business-readiness-brief.md`: not on `main`, on any branch checked, or in the
project's shared files. It starts here, written from Jay's messages and the pull requests. The brief's own text (its D
and F items, its acceptance lines) was not available, so each item below is described in the words of Jay's messages
and the pull request that delivered it, and where a PR names a D or F item it is the label Jay's message gave.

## Phase A

| Item | What it asked | Pull request | State |
|---|---|---|---|
| A1 (D5, F3) | The demo starts as its first Admin; a station starts with the user who signed in last | #397 | Merged 2026-10-12 |
| A2 (D6, F4) | A control a role may not use is greyed with the reason, never hidden | #398 | Merged 2026-10-12 |
| A3 (D3, F5) | A board model's first AI model goes live when trained | #399 | Merged 2026-10-12 |
| A4 (D7 part, F10) | Reset Demo inside the presenter theme in three clicks; the Admin keeps Settings | #400 | Merged 2026-10-12 |
| A5 (F8) | Demo-path messages in plain words, details behind Show Details | #401 | Merged 2026-10-12 |
| A6 (F12) | A second start brings the open copy to the front, else one sentence and one button | #402 | Merged 2026-10-12 |
| A7 (#104, Charter principle 1) | Every page the demo scripts visit fits the presenter theme at 1366 × 768, its verdict area unscrolled | #403 | Open: the 16 pt size waits for Jay |
| A8 (F14) | Click the 45-minute script; the 5-minute one at 1366 × 768; a crash-recovery test | #404, stacked on A7 | Open |

The Phase A report follows A8, at the end of this file.

## Phase A report, 2026-10-12

Phase A asked that a presenter can run the Stage 1 demo for a customer without it going wrong in front of them. Every
item has a pull request: A1 to A6 are merged into `main`, and A7 and A8 are open, stacked in that order, for Jay's
review. Each item's test runs on every pull request. The demo's boards are drawn, so nothing here is a measure of
accuracy.

### What each item delivered

| Item | Pull request | Its test | Its screen |
|---|---|---|---|
| A1 (D5, F3) The demo starts as its first Admin; a station starts with who signed in last | #397, merged | `tests/test_start_user.py` (6 tests), among them `test_req_set_007_main_demo_starts_as_the_first_admin_at_home_in_its_theme_within_5_s` | No approved screenshot moved; the status bar names the user signed in |
| A2 (D6, F4) A control a role may not use is greyed with the reason, never hidden | #398, merged | `tests/test_role_gates.py` (8 tests), among them `test_req_usr_001_no_screen_hides_a_control_for_a_role` | All 20 approved screenshots re-approved: every page for every role, greyed controls with their reason |
| A3 (D3, F5) A board model's first AI model goes live when trained | #399, merged | `tests/test_first_model_live.py` (7 tests) | No approved screenshot moved; the line naming a version that is not active shows only when there is one |
| A4 (D7 part, F10) Reset Demo in the presenter theme in three clicks; the Admin keeps Settings | #400, merged | `test_req_set_008_in_the_presenter_theme_an_admin_resets_the_demo_or_leaves_the_theme_in_three_clicks` (at 1366 × 768 since A7) | `presenter-settings-admin.png` (new), `presenter-home-admin.png`, `settings-*.png` |
| A5 (F8) Demo-path messages in plain words, details behind Show Details | #401, merged | `tests/test_demo_path_messages.py` (24 tests): 64 codes the demo can raise, scanned for an exception's class, system text or a tool's path | No approved screenshot moved; the messages' text changed |
| A6 (F12) A second start brings the open copy to the front, else one sentence and one button | #402, merged | `tests/test_second_start.py` (14 tests, 2 of them on Windows CI only) | No approved screenshot moved; AOI-SET-019's box is new |
| A7 (#104) Every page the demo scripts open fits 1366 × 768 in the presenter theme, its verdict area unscrolled | #403, open | `tests/test_demo_fit.py` (every page and tab the scripts open, both themes, at 1366 × 768, then at 1500 × 1000 and 1920 × 1080, then at 1366 × 768 again) | `presenter-1366-*.png` (8 new, 1366 × 768); 23 approved screenshots moved at 1920 × 1080 (listed in #403) |
| A8 (F14) The 45-minute script clicked through; the 5-minute one at 1366 × 768; a crash-recovery test | #404, open | `test_req_set_007_the_forty_five_minute_script_clicked_through`, `test_req_set_007_the_five_minute_script_runs_in_the_presenter_theme[1366x768]`, `test_req_set_007_a_demo_closed_mid_run_opens_again_as_the_demo_kit_says[crash]` and `[close]`; each asserts no dialog | No screen changed (tests and the demo kit only) |

The least window each demo page needs, in both themes, is in [docs/tests/2026-10-screen-sizes.md](../tests/2026-10-screen-sizes.md).

### Still open, and who closes it

**Jay decides** (each was put to Jay on 2026-10-12 and is not yet answered):

1. **16 pt presenter text in a small window** (A7). REQ-SET-008, a MUST, proposes 18 pt; at 18 pt the verdict area
   cannot be whole at 1366 × 768. Approving it closes REQ-SET-008, which reads Partial until then; "Keep 18 pt" reverts
   ADR 0019's decision 2 and sends a 1366 × 768 projector back to the recording.
2. **The production theme's Compare stacks below 1848 px** (A7), which amends ADR 0012's decision 2: at 1600 × 900 the
   decision table is whole and the Try panel's Re-evaluate and Save to Recipe sit just below the fold.
3. **A full-screen presenter view** (A7). Maximized on a 1366 × 768 Windows screen the app has about 1366 × 697, where
   Inspection's Start and the last two rows of Compare's table sit just below the edge. Recommended: build it as its own
   pull request after Phase A.
4. **Review and merge #403, then #404** (CLAUDE.md rule 6).
5. **The brief and this file.** `docs/plans/2026-10-business-readiness-brief.md` is not in the repository, so this report
   follows Jay's messages, not the brief's acceptance lines. Adding the brief lets the report be checked against it.

**Claude builds, once Jay says so:**

- Defect-box labels at a picture's edge can be cut off ("3 Anomaly ■ Major" past the right edge), and `cut_off` does not
  check labels (A7 review; also so before A7).
- Reset Demo lets go of the demo's lock while the demo is copied back, so a second start in that moment could open a
  half-copied demo (A6).
- A message box's OK and Show Details… buttons keep Qt's own size, not the 48 px target (A5).
- Settings' Dataset stores table is cut at 18 pt in the presenter theme; the 45-minute script leaves the theme for that
  step (A4).
- The go-live gate's comparison on the locked validation set (REQ-TRN-012, release 1.0), and a stored result judged
  while a trained version waited still says no AI model was trained (A3). The Engineering standard's go-live text needs
  D3's exception, which is Jay's to write.

**People, on the demo laptop or the release build:**

- REQ-SET-004's human review of the pages on a 1366 × 768 projector and at 4K with 150 to 200 % scaling, from the back
  row (A7): not done. The sizes here were measured on Linux with DejaVu Sans; Windows draws Segoe UI, which CI's
  Windows run checks and a stand-in font for it checked here (#403).
- Customers & Launch asks that someone in each reader's role follows the scripts on the release build before they go
  out; the release build does not exist yet.
- The Korean drafts (the release note, the demo kit) need a native speaker who knows SMT terms (REQ-SET-006).
- A6 was not tried on a PC with two Windows accounts or over a remote desktop; its Windows-only tests run on CI.
