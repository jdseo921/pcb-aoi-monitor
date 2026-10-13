# Screen sizes of the demo's pages, 2026-10-12

How large a window each page and tab the three demo scripts open needs, in the presenter theme at its two sizes and in
the production theme: A7 of the 2026-10 business-readiness brief (#104, Charter principle 1), which asks that every
such page fits the presenter theme at 1366 × 768 with no scrolling in its verdict area. ADR 0019 records the layout
decisions; `tests/test_demo_fit.py` checks the result at 1366 × 768 on every pull request.

**Synthetic boards only.** The pages show the demo bundle's drawn boards (`tools/make_demo_bundle.py`). The sizes
depend on what a page shows, never on how well it judges; nothing here is a measure of accuracy.

## Set-up

- Branch `feat/REQ-SET-008-presenter-1366` on `0b39d3d` (main after A6), with this change's layout work.
- Linux container, Python 3.13.16, PySide6 6.11.2 (Qt 6.11.2), `QT_QPA_PLATFORM=offscreen`, DejaVu Sans without
  hinting, as the approved screenshots are drawn (`tools/render_screens.py`, `pinned_rendering`). Windows draws Segoe
  UI, whose widths differ by a few pixels; these numbers were not taken on Windows.
- `python tools/screen_sizes.py --bundle <demo bundle>`: the demo loaded into a temporary workspace, signed in as the
  Admin, the 5-minute script's run paused at its NG board (board_04.png), that board open on Compare and selected on
  Logs & Export, and AI Model Test run once on the demo's locked validation set. Each page is measured on the tab it
  opens on and on each tab the 45-minute script opens there (`DEMO_TABS`), the window resized and laid out (`settle`)
  before each reading, in the order the tool visits them: each theme in turn, and in it each page from a window
  2560 px wide down to its narrowest and back.
- The window is measured inside its frame, as Qt sizes it. Windows takes the title bar (31 px at 100 % scaling) and
  the taskbar (40 px on Windows 10, 48 px on Windows 11) off the screen's height, so a window maximized on a
  1366 × 768 screen measures about 1366 × 697 on Windows 10 and 1366 × 689 on Windows 11; the last column reads the
  page at 1366 × 697.

## What is measured

- **Narrowest, 768 px tall**: the narrowest window 768 px tall in which the page does not scroll across.
- **Nothing cut off, 1366 px wide**: the shortest window 1366 px wide in which `cut_off` finds nothing: on Inspection,
  Compare and Logs & Export the verdict area (`VERDICT_AREA`) whole with nothing scrolled (on Inspection the verdict,
  the board with every defect box in view, the line under the verdict, the defect list with no scroll bar, the review
  buttons, Compare with Golden board › and Start; on Compare the pair, the verdict and the decision table with every
  check and column in view; on Logs & Export the summary line), and on every page no text cut off across or down and
  no scroll bar across, on the page or on a panel of fields in it. On a page with no verdict area and nothing cut off
  at any height, it is the window's least height (195 to 201 px). "none; N px across at least": no window 1366 px wide
  is enough, and N is the narrowest window, 2400 px tall, that is.
- **No scrolling, 1366 px wide**: the shortest window 1366 px wide in which the page needs no scroll bar at all.
- **At 1366 x 697 (maximized)**: what `cut_off` finds in that window; "fits" when nothing.

## Results

### Presenter theme, 18 pt (a window 900 px tall and 1400 px wide or more)

| Page | Narrowest, 768 px tall | Nothing cut off, 1366 px wide | No scrolling, 1366 px wide | At 1366 x 697 (maximized) |
|---|---|---|---|---|
| Home | 1247 | 201 | 843 | fits |
| Inspection | 1235 | 813 | 923 | view is not whole; review is not whole; btn_compare is not whole; btn_start is not whole |
| Compare | 1235 | none; 1389 px across at least | 1179 | metrics is not whole; metrics scrolls across |
| Training | 1305 | 201 | 1445 | fits |
| Training, Datasets tab | 1305 | 201 | 1445 | fits |
| AI Model Test | 1235 | 201 | 946 | fits |
| AI Model Test, History tab | 1235 | 201 | 777 | fits |
| Recipe Editor | 1249 | 201 | 832 | fits |
| Recipe Editor, Thresholds tab | 1249 | 201 | 832 | fits |
| Recipe Editor, AOI checks tab | 1249 | 201 | 832 | fits |
| Recipe Editor, Revisions tab | 1249 | 201 | 832 | fits |
| Logs & Export | 1235 | 650 | 816 | fits |
| Settings | 1246 | 201 | 1363 | fits |

### Presenter theme, 16 pt (a window under 900 px tall or under 1400 px wide)

| Page | Narrowest, 768 px tall | Nothing cut off, 1366 px wide | No scrolling, 1366 px wide | At 1366 x 697 (maximized) |
|---|---|---|---|---|
| Home | 1163 | 197 | 787 | fits |
| Inspection | 1157 | 750 | 860 | btn_start is not whole |
| Compare | 1157 | 718 | 1052 | metrics is not whole |
| Training | 1189 | 197 | 1416 | fits |
| Training, Datasets tab | 1189 | 197 | 1416 | fits |
| AI Model Test | 1157 | 197 | 892 | fits |
| AI Model Test, History tab | 1157 | 197 | 759 | fits |
| Recipe Editor | 1211 | 197 | 789 | fits |
| Recipe Editor, Thresholds tab | 1211 | 197 | 789 | fits |
| Recipe Editor, AOI checks tab | 1211 | 197 | 789 | fits |
| Recipe Editor, Revisions tab | 1174 | 197 | 789 | fits |
| Logs & Export | 1157 | 588 | 706 | fits |
| Settings | 1157 | 197 | 1277 | fits |

### Production theme (dark, 14 pt)

| Page | Narrowest, 768 px tall | Nothing cut off, 1366 px wide | No scrolling, 1366 px wide | At 1366 x 697 (maximized) |
|---|---|---|---|---|
| Home | 1085 | 195 | 701 | fits |
| Inspection | 1013 | 755 | 865 | btn_start is not whole |
| Compare | 1129 | 737 | 1071 | metrics is not whole |
| Training | 1115 | 195 | 893 | fits |
| Training, Datasets tab | 1115 | 195 | 893 | fits |
| AI Model Test | 877 | 195 | 851 | fits |
| AI Model Test, History tab | 877 | 195 | 749 | fits |
| Recipe Editor | 1154 | 195 | 774 | fits |
| Recipe Editor, Thresholds tab | 1154 | 195 | 774 | fits |
| Recipe Editor, AOI checks tab | 1154 | 195 | 774 | fits |
| Recipe Editor, Revisions tab | 1130 | 195 | 774 | fits |
| Logs & Export | 877 | 582 | 700 | fits |
| Settings | 1276 | 195 | 1121 | fits |

## Before

On `main` at 0b39d3d, measured the same way (the same demo state, fonts and tabs), no page the demo opens fitted a
1366 px window: in a window 768 px tall each scrolled across below 1774 to 1820 px in the presenter theme (the window
could not be made narrower than 1527 px) and below 1679 to 1725 px in the production theme (1220 px).

## Reading

- At 1366 × 768 every page and tab the scripts open fits, in the presenter theme (16 pt there) and in the production
  theme: none scrolls across in a window 1211 px wide or wider in the presenter theme, or 1276 px in the production
  theme, and the verdict areas need a window 750 px tall (Inspection), 718 px (Compare) and 588 px (Logs & Export) in
  the presenter theme, 755, 737 and 582 px in the production theme. `tests/test_demo_fit.py` checks both themes at
  1366 × 768, also after each page was shown at 1920 × 1080, and the verdict areas at 1500 × 1000 and 1920 × 1080.
- The presenter theme takes 16 pt only in a window under 900 px tall or under 1400 px wide (ADR 0019, decision 2): at
  18 pt, Compare's decision table needs a window 1389 px wide, which a 1280 × 1024 screen does not give, and
  Inspection's verdict area a window 813 px tall. `tools/screen_sizes.py` holds each size whatever the window, so both
  are measured at 1366 px.
- Compare puts its decision table under the pair below 1848 px in the production theme, 1928 px at 16 pt and 2048 px at
  18 pt, the width the pair needs beside the table at `theme.DECISION_W` (900, 980 and 1100 px; the demo's NG board
  fills the table 893, 975 and 1099 px wide). The verdict, its note and the "why" box then stand beside the pair.
- In a window maximized on a 1366 × 768 Windows screen (about 1366 × 697, or 689 on Windows 11), Inspection's Start sits
  under the bottom edge (53 px short at 16 pt, 58 px in the production theme, 8 px more on Windows 11) and so does the
  foot of Compare's table: its last row at 16 pt (21 px short), its last two, the demo board's AI score among them, in
  the production theme (40 px). Windows' Segoe UI draws taller lines: with a stand-in for it (DejaVu Sans given Segoe
  UI's line height and 0.85 of its widths), the last two rows are under the edge at 16 pt too (50 px short). The
  verdict, the board with its defect boxes, the defect list, the review buttons and Compare with Golden board › are in
  view; F5 starts the run with Start out of view. Since Jay's choice of 2026-10-13 the presenter theme opens full
  screen (ADR 0019, decision 4), so a demo has the whole 1366 × 768 and this column applies to the production
  theme's maximized window, and to a presenter window someone sized by hand to it before switching the theme on.
- Pages other than these three may scroll below the fold, their lower panels secondary to what the scripts show first:
  at 1366 px wide and 16 pt, Training needs 1416 px of height with nothing scrolled, Settings 1277 px, AI Model Test
  892 px, Recipe Editor 789 px and Home 787 px.
- Training's lines were cut short after a window 2560 px wide until its groups of wrapped lines held their height at
  each width (`WrappedGroup`); the column "Nothing cut off" reads them in that order, and `tests/test_demo_fit.py`
  checks it.
