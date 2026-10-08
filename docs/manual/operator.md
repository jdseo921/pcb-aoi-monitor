# Operator manual (draft)

For the person running boards on the line. Each section is filled in by the stage that delivers the feature
(Engineering, "Docs as code": the manual changes in the same pull request as the feature). Screenshots are
regenerated from the release build before a release (Customers & Launch, "Tried by a reader").

Words: verdicts are OK, NG and WARN (양품, 불량, 확인 필요); see the Charter's glossary.

## 1. Starting a shift

(to be written: picking your name, the board model, the view)

## 2. Running boards

Queue the boards with **Load Images…** (Ctrl+O) or **Load Folder…** (Ctrl+Shift+O); the count of queued images shows
at the right of the top bar. Pick the view the boards are photographed from in the **View** box (Top, Side or Bottom),
or cycle it with Alt+V; the view is stored with every result.

| Control | Key | What it does |
|---|---|---|
| ▶ Start | F5 | Inspects the queue board after board, until Stop or the end of the queue |
| ■ Stop | F6 | Stops after the board in hand; nothing is deleted, so there is no confirmation |
| Next Board | F8 | Inspects one board |
| Save Image… | F9 | Writes the board image with its defect boxes to a picture file you choose; the result itself is already recorded |

A button and its key do the same. The key works whichever control on the Inspection page is selected (the defect
list, the View box, a button), and only while that page is shown. Both go grey while the action is not possible:
Start and Next Board until images are queued, while a run is on and while a board is being inspected; Stop while no
run is on; Save Image… before the first result. Every result is recorded as it arrives, with the checks that decided
it, before the next board starts; the records are on Logs & Export. If a result cannot be recorded (the disk is full,
the workspace folder cannot be written, another program holds the database) the run stops with AOI-INSP-008: press
Next Board to carry on, and inspect that board again later; such a board is not on Logs & Export and, if NG, has no
alarm. An NG board that is recorded always has its NG alarm (AOI-INSP-003). Closing the app while a board is being
inspected asks whether to stop: No keeps the app open; Yes records the board in hand and closes.
A run belongs to the board model it was started under. If the board model in the header changes during a run, the run
stops after the board in hand, which is saved under the run's board model, and the status bar and the alarm log say so
with AOI-INSP-012; the remaining boards are not inspected. Check the board model in the header, then press Start to
carry on with the queue. The board shown before the change is cleared, so "Compare with Golden board ›" never opens it
as a board of the new board model.
A run also belongs to the user who pressed Start. If another user signs in with Switch User during a run, the run stops
after the board in hand, which is recorded under the user who pressed Start, and the status bar says so; the user now
signed in presses Start to carry on with the queue, and those boards are recorded under their name.

Reading the verdict: while a board is being inspected the banner turns grey and reads "Inspecting…", and the status
bar at the bottom names the board and its place in the queue, such as "Inspecting board_07.png (3 of 12)…". The
verdict then fills the banner: ✓ OK on green, ✗ NG on red, ▲ WARN on amber, with the defect list under it (section 3),
and the status bar shows the board's summary line: file, AI score, defects and time.
A board the app cannot read stops the run with a message that says what happened and what to do, and the banner keeps
the last verdict; press Next Board to go on with the queue. A board is never passed on no evidence: the run stops the
same way when the Golden board's file is gone or damaged (AOI-INSP-009), when nothing can judge the board because the
board model has neither a Golden board nor an AI model yet, or the recipe turns both off (AOI-INSP-010), and for a
picture under 11 px on a side (AOI-INSP-011); for the first two, call an Engineer. At the end of the queue the status bar reads "End of
queue".

## 3. When a board is NG or WARN

The defect list under the banner names each defect with its number, type, score, side and position; click a row to
zoom the picture to it. Press "Compare with Golden board ›" (or open Compare from the sidebar and press Use Last
Inspected) to see the board as it was judged, lined up with the Golden board it was judged against, and the decision table that
produced the verdict: every check with its source, value, threshold, rule and result, the failing rows in red or amber,
exactly as they were decided and stored; the board is not inspected again. The "why" box under the table explains
the verdict in plain words, under the heading "Why this board is NG:": one sentence per failing check, the NG ones
first, naming the check, its value and its threshold with their unit ("The changed area is 2.35 % of the board, at or
above its threshold of 0.50 %."; an ROI's value is a multiple of the AI model's threshold, "2.00 ×"). With no failing
check it says that every check that decides the verdict is inside its threshold or, for a WARN, that defects above
Minor severity are marked on the board, so a person needs to look. A sentence for each check that did not run (no
Golden board set, or no AI model trained) says what to do; the Inspection page shows it under its summary too. A line
under the verdict says when the result was judged and with which AI model version and recipe
revision; when an Engineer has changed either since, it says so, and the table still shows the thresholds that applied
at the time. When the result's heatmaps are no longer stored (OK results lose them after the retention period), the
line says so with the code AOI-CMP-001, and the Side by side and Boxes only views still work. When the stored picture
itself was deleted, the page says "Board picture no longer stored", the table still stands, and Re-evaluate inspects
the board again from its image file. The Golden board
pane names the file the result was judged against. When that file has changed, cannot be read or is gone, or the
result names none (it was judged without one, or saved before this version), the pane says "Golden board not
available" and why, rather than show today's Golden board, and Re-evaluate under it inspects the board again with
today's; the line under the verdict names today's when an Engineer or a training run has set another.

## 4. Alarms and messages

(to be written: the alarm log, error codes and what to do)

## 5. End of shift

(to be written: history and export, handing over)
