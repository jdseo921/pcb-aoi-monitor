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
| A7 (#104, Charter principle 1) | Every page the demo scripts visit fits the presenter theme at 1366 × 768, its verdict area unscrolled | #403 | Merged 2026-10-13 |
| A8 (F14) | Click the 45-minute script; the 5-minute one at 1366 × 768; a crash-recovery test | #404 | Merged 2026-10-13 |
| A7 follow-up (#104) | The presenter theme fills the whole screen (Jay's choice of 2026-10-13) | #405 | Merged 2026-10-13 |

The Phase A report, written before #403 to #405 were merged, is at the end of this file, after Phase B.

## Phase B

Jay's message of 2026-10-13 06:06 UTC asked for B1 and B2 of the brief, one stacked pull request each, and named
`docs/adr/0014-stage1-for-one-person.md` and the brief as the approval for the MUST requirements they change. Neither
file is in the repository, and the repository's ADR 0014 is the master samples record, so B1's record is ADR 0020 and
B2's is ADR 0021; each says that Jay's record wins where it decides otherwise.

Jay's message of 2026-10-13 14:22 UTC asked for B3 and B4, one stacked pull request each. The brief is still not in
the repository, so each follows the words of that message: B3's record is ADR 0022 and B4's is ADR 0023, and each
says that Jay's record wins where it decides otherwise. #406 and #407 were not merged, so B3 is stacked on #407 and
B4 on B3.

| Item | What it asked | Pull request | State |
|---|---|---|---|
| B1 (D1, F1, F2) | One person freezes, splits and locks a Trial version and trains from it, with no second-user label check and no agreement check; Trial is said wherever the version or its AI model is named; the go-live gate and the customer validation report refuse it, with Start the Checks | #406 | Open, for Jay's review |
| B2 (D2, F2, F13) | A customer's first board model makes the customer's encrypted store in the same dialog; the recovery key is shown once, with Save to File…, Print… and a tick that cannot be skipped; key ids, Restore Key… and Shred Store… move under an Admin's Advanced tick | #407, stacked on #406 | Open, for Jay's review |
| B3 (F6) | One sentence, computed from the constants in `aoi/core/datasets.py`, wherever the images a board model needs are stated; Home and Training list what the selected board model still needs, each line a count against its need with the one button that takes the step; a Trial list shows only what Trial needs, a Validated one adds the second-user checks and the agreement check | #408, stacked on #407 | Open, for Jay's review |
| B4 (D4 part, F9) | A board model's name is checked where it is entered, with the rule freeze applies (AOI-TRN-039): a name with no Latin letter or digit, such as a Korean-only one, is refused at entry with AOI-TRN-054, whose message says what a valid name looks like | #409, stacked on #408 | Open, for Jay's review |
| B4 follow-up (Jay's decision, 2026-10-13 19:58 UTC) | A new name that reads the same as an existing one on a screen (case, full-width letters or digits, a no-break or zero-width space, a decomposed Hangul syllable set aside) is refused at entry with AOI-TRN-055, and one whose letters A to Z and digits are an existing name's, which freeze refused only once the other had a version (AOI-TRN-040), with AOI-TRN-056 | #410, stacked on #409 | Open, for Jay's review |

Choices made in Phase B, each recorded in its ADR:

- **Memory-only keys (B2): refused.** On a system whose key store keeps keys in memory only (any but Windows), a
  customer's store is not made (AOI-TRN-053, which says why and that nothing was made), and the install guide says so
  too. The refusal reads a flag that only the station's own memory key store sets, so the tests on Linux CI, which keep
  their keys, are unaffected (ADR 0021, decision 4).
- **A Trial AI model never goes live (B1).** Jay's message says the go-live gate refuses a Trial version. This is the
  recommended option ("Never live") of the card put to Jay on 2026-10-13 06:15 UTC, not yet answered; the others were
  "Live, marked Trial" and "Live until Validated" (ADR 0020, decision 4). The first AI model trained from a Validated
  version after Trial ones goes live, as a board model's first does (ADR 0018).
- **What is missing counts per view (B3).** A dataset version is of one view, so 40 Top and 40 Side images do not
  meet the 70. A board model needs 1 NG image or more, which nothing required before, and a Validated one a line of
  its own for the agreement check's 100 images; a Trial list ends at a trained AI model, since a Trial AI model
  never goes live. Each button waits only for what its own step checks, so images added after a freeze never grey
  the version frozen before (ADR 0022).
- **A new code for a name refused at entry (B4).** AOI-TRN-054 says what to type now; AOI-TRN-039 stays for a
  board model made before the rule, which keeps its name and is refused only at freeze, as before. "기판 2호" is
  taken, because its digit names its versions (ADR 0023).
- **Look-alikes are compared, not stored normalised (B4 follow-up).** A name is kept as typed; two names are alike
  when they read the same in NFKC, case folded, with the characters that show nothing dropped and spaces of any kind
  as one. Cyrillic or Greek letters that look like Latin ones, and O and 0, are not compared as alike (ADR 0023,
  decisions 6 to 8).
- `tests/regression/expected.json` is byte-identical in every pull request of Phase B: no verdict changes.

Still open after Phase B:

1. **Jay decides** the "Never live" card, and reviews and merges #406, then #407, then #408, then #409, then
   #410 (CLAUDE.md rule 6).
2. **Decided by Jay** on 2026-10-13 19:58 UTC: a name whose versions would take another board model's names, and a
   name that looks like another, are refused at entry (#410; ADR 0023, decisions 6 to 8).
3. **Jay adds** the brief and the "Stage 1 for one person" ADR to the repository, under a free ADR number, and writes
   D1's exception into the Engineering standard's text about the label and agreement checks.
4. **People:** the Korean strings the items add are drafts, many unfinished in `aoi_ko.ts`, for a native speaker who
   knows SMT terms; Save to File… and Print… of a recovery key were not tried on the Windows station or a real printer.
5. **Claude fixes, once Jay says so:** training a board model again, as AOI-TRN-012 asks for an AI model whose
   registry row cannot be read, would stop at `trial_version` in `AppContext.train` (#406). Found while building B3,
   inferred from the code and not run; B3's own list skips such a row.

## Phase A report, 2026-10-12

Phase A asked that a presenter can run the Stage 1 demo for a customer without it going wrong in front of them. Every
item has a pull request: A1 to A6 are merged into `main`, and A7 and A8 are open, stacked in that order, for Jay's
review, with the full screen Jay chose on 2026-10-13 stacked after them. Each item's test runs on every pull request.
The demo's boards are drawn, so nothing here is a measure of accuracy.

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
| A7 follow-up (#104) The presenter theme fills the whole screen; Exit presenter theme gives the window back | #405, open | `test_req_set_008_the_presenter_theme_fills_the_screen_and_its_exit_gives_the_window_back`, `test_req_set_008_a_switch_to_full_screen_styles_the_app_once_at_the_screens_size`, `test_req_set_008_the_presenter_theme_fills_the_projector_and_a_workspace_switch_stays_on_it` (a laptop and a projector beside it); the 5-minute script and the crash-recovery test check how each window is shown | The six Settings screenshots, for the Presenter theme's description ("Full screen and light, …") |

The least window each demo page needs, in both themes, is in [docs/tests/2026-10-screen-sizes.md](../tests/2026-10-screen-sizes.md).

### Still open, and who closes it

**Jay decides** (each was put to Jay on 2026-10-12; the first two are not yet answered):

1. **16 pt presenter text in a small window** (A7). REQ-SET-008, a MUST, proposes 18 pt; at 18 pt the verdict area
   cannot be whole at 1366 × 768. Approving it closes REQ-SET-008, which reads Partial until then; "Keep 18 pt" reverts
   ADR 0019's decision 2 and sends a 1366 × 768 projector back to the recording.
2. **The production theme's Compare stacks below 1848 px** (A7), which amends ADR 0012's decision 2: at 1600 × 900 the
   decision table is whole and the Try panel's Re-evaluate and Save to Recipe sit just below the fold.
3. **A full-screen presenter view** (A7): answered. Jay chose "Full screen" on 2026-10-13 00:51 UTC. The presenter
   theme now fills the screen, so Inspection's Start and the last two rows of Compare's table, which sat just below
   the edge of a window maximized on a 1366 × 768 screen, are in view; Exit presenter theme gives the window back.
   Built in #405, stacked on #404 (ADR 0019, decision 4).
4. **Review and merge #403, then #404, then #405** (CLAUDE.md rule 6).
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
