# ADR 0019: The demo's pages fit a 1366 × 768 window, the presenter theme at 16 pt in a small one

- Status: Proposed under Jay's instruction of 2026-10-12 12:53 UTC, item A7 of the business-readiness brief (#104,
  Charter principle 1): "every page the three demo scripts visit fits the presenter theme at 1366×768 with no
  scrolling in the verdict area (verdict, defect boxes, the Compare pair and its table, the Logs summary line);
  scrolling is allowed only in secondary panels below the fold". The 16 pt size of decision 2 was put to Jay as a
  choice on 2026-10-12 and is not yet answered; Jay's merge of this record accepts it, and "Keep 18 pt" instead
  reverts decision 2 (Consequences). Decision 4 is Jay's choice of 2026-10-13 00:51 UTC: "Full screen", on the
  question "Make the presenter theme fill the whole screen, so a maximized 1366 × 768 projector shows every verdict
  area?".
- Date: 2026-10-12
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-SET-004, REQ-SET-008, ADR 0012 (decision 2 and its alternatives), #104, `theme.SMALL_H`,
  `theme.PRESENTER_SMALL`, `theme.DECISION_W`, `MainWindow.show_for_theme`, `FlowLayout`, `ReflowSplitter`, `SideSplit`, `WrappedPane`,
  `WrappedGroup`, `tools/screen_sizes.py`,
  `tests/test_demo_fit.py`, [the measurements](../tests/2026-10-screen-sizes.md)

## Context

ADR 0012 kept 1920 × 1080 as the reference screen and let a smaller one scroll, with nothing hidden. A projector in a
customer's meeting room often takes only 1366 × 768, and there the demo did not fit: in the presenter theme every page
the demo opens scrolled sideways in a window narrower than 1774 to 1820 px (1679 to 1725 px in the production theme,
measured on `main` at 0b39d3d), and the verdict, Compare's pair and its table could not all be seen at once. The demo
kit told the presenter to play the recording instead.

At the presenter theme's 18 pt, Compare's decision table is 1099 px wide with every column whole; a 1366 px window
leaves the page about 1060 px beside the sidebar. Inspection's verdict panel (the verdict, the line under it, the
defect list, the review buttons and Compare with Golden board ›) with the run controls under it needs a window 813 px
tall, 45 px more than 768 (docs/tests/2026-10-screen-sizes.md).

## Decision

1. **The pages a demo opens reflow below 1920 px, so none scrolls across at 1366 px.** A row of buttons or fields
   wraps onto a second row (`FlowLayout`, `aoi/ui/widgets/flow.py`); two panes side by side stack when the page is
   narrower than both need (`ReflowSplitter`, `aoi/ui/widgets/reflow.py`); a side panel beside a picture keeps the
   width it asks for while the picture keeps its least width (`SideSplit`); a pane of wrapped text takes the height
   its text needs at its width (`WrappedPane`), a group of wrapped lines holds that height too (`WrappedGroup`), and an
   empty state's host grows to its text; a form's field goes under its label (`WrapLongRows`). Compare puts its
   verdict, its note and the "why" box beside the pair and the decision table, whole, under them, where the pair and
   the table do not fit side by side; the table is as tall as its rows, and the boards take the rest. The window
   decides that, not the record shown: the table is counted at `theme.DECISION_W`, the width it takes
   with every column whole as the demo's NG board fills it in the theme's text size (900, 980 and 1100 px at 14, 16
   and 18 pt), so opening a record never turns the page; side by side, the pair gives the panel the table's own width
   (`Compare._keep_table`). A button never shrinks below its label (`pages/base.py`,
   `_Button`): it moves to the next row instead. At 1920 × 1080 the pages are laid out as before, but for the changes
   the release note lists.
2. **The presenter theme takes 16 pt text and a 44 pt verdict in a window under 900 px tall or under 1400 px wide**
   (`theme.SMALL_H`, `theme.SMALL_W`, `theme.PRESENTER_SMALL`, `MainWindow._small`), and its 18 pt and 48 pt again in a
   larger one, as the window is resized. On a projector, text height is a share of the picture: 16 pt in 768 lines is
   2.8 % of the wall, larger than 18 pt in 1080 lines (2.2 %), and 16 pt in 1024 lines is 2.1 %, so the back row reads
   it about as well as the presenter theme's text at 1920 × 1080 or better. The window decides, not the screen: 1920 ×
   1080 gives a maximized window of about 1000 px, every 1366 × 768 window is under 900, and at 18 pt Compare's
   decision table needs a window 1389 px wide, which a 1280 × 1024 screen does not give. REQ-SET-004's floors stay
   met: text 14 pt or more, the verdict 40 pt or more, targets 48 px.
3. **What must be seen without scrolling is the verdict area**, and `tools/screen_sizes.py` names it (`VERDICT_AREA`):
   on Inspection the verdict, the board with its defect boxes, the line under the verdict, the defect list, the review
   buttons, Compare with Golden board › and Start; on Compare the pair, the verdict and every check of the decision
   table; on Logs & Export the summary line. Everything else may sit below the fold and scroll, as ADR 0012 allows.
   `tests/test_demo_fit.py` checks it on every page the scripts open, in a 1366 × 768 window, in both themes, and the
   approved screenshots `presenter-1366-*.png` show those pages at that size.
4. **The presenter theme fills the whole screen** (`MainWindow.show_for_theme`). A window maximized on a 1366 × 768
   Windows screen has about 1366 × 697 (689 on Windows 11), as the title bar and the taskbar keep their share, and
   there Inspection's Start and the last two rows of Compare's table, the demo board's AI score among them, sat
   below the edge; full screen gives the pages all 768 px, which decisions 1 to 3 fit. The app opens full screen with
   the theme saved on (a start, Load Demo, Reset Demo), goes full screen when an Admin ticks Presenter theme in the
   window the app opened, and gives back the maximized window with Exit presenter theme; a window someone sized by
   hand keeps its size either way. The production theme opens maximized, with its title bar, as before. The switch
   styles the pages once, at the size of the screen the window goes full screen on. No key switches it: F11, the
   usual one, is False call on Inspection and Logs & Export; Alt+Tab and Alt+F4 work as in any window.

This narrows ADR 0012's third alternative ("lay every page out to fit 1366 × 768 without scrolling"): only the
verdict area is laid out to fit, and the rest of each page still scrolls.

## Alternatives

- Keep 18 pt at 1366 × 768: Compare's decision table needs 1099 px and Inspection's run controls fall 45 px
  below the fold, so the verdict area cannot be whole; the demo kit would keep telling the presenter to play the
  recording there.
- A smaller presenter size on every screen: the presenter theme at 1920 × 1080 would lose size it has room for.
- Switch on the screen's size, not the window's: a window the presenter sizes by hand, or one on a second screen,
  would get the wrong size; the window's size is what the layout has.
- A table that scrolls across on Compare: the verdict's reasons would hide in the scrolled part, which A7 forbids.
- Stay maximized in the presenter theme, with the demo kit telling the presenter to press F5 to start and to scroll
  Compare for its last rows (as A7 was first built): the demo board's AI score would be out of view as the customer
  reads the verdict.

## Consequences

A window that crosses 900 px of height or 1400 px of width restyles every page once, as switching the theme on does;
before the window is first shown, and while it is full screen, the screen's room decides, so a start, or a switch
to full screen, styles it once. The presenter theme's
screenshots at 1920 × 1080 keep 18 pt; `presenter-1366-*.png` show 16 pt.

In the presenter theme Compare puts its decision table under the pair at 1920 × 1080 too, where at 18 pt the table does
not fit beside it (the page turns at 2048 px), and the 5-minute script points at it there. The production theme's
Compare does the same in a window under 1848 px wide, as at 1600 × 900: there the table, beside the pair, scrolled its
last columns out of view, and now the foot of Try other thresholds, a secondary panel, its buttons with it, may sit just
below the fold instead, which Tab and the scroll wheel reach (decision 3); this amends ADR 0012's decision 2. Beside the
pair, the "why" box takes the height under the note, `theme.WHY_H` at least (150 px, and 110 px at the presenter theme's
16 pt: four lines of DejaVu Sans, three and a part of Windows' Segoe UI, where asking for 150 px put the table's last
row below a 1366 × 768 window), and under the table it is `theme.WHY_H` at most: its reasons show whole at 1920 × 1080
and scroll within the box at 1366 × 768, where under the table it would sit below the fold; while "Re-evaluating…"
covers the table, a cover of its own covers the box. With the table under the pair, Defect boxes only fits the test
board to the pair's height, so it draws the board about as large as Side by side does, not larger as it does beside the
table.

A window maximized on a 1366 × 768 Windows screen measures about 1366 × 697 (1366 × 689 on Windows 11), not
1366 × 768, as the title bar and the taskbar take their part of the screen; what that window shows is measured in the
record above. The presenter theme opens full screen there (decision 4), so a demo has the whole 1366 × 768. The
production theme, maximized, keeps the gap: on a 1366 × 768 station Inspection's Start and the foot of Compare's
table sit just below the edge, which F5 and the scroll wheel reach; ADR 0012's reference screen, 1920 × 1080, does
not have it.

If Jay picks "Keep 18 pt", `PRESENTER_SMALL` and `SMALL_H` go, decision 1 stays, and the demo kit goes back to the
recording for a 1366 × 768 projector. No verdict changes: this is layout and text size only.
