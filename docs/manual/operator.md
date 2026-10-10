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
| Save Image… | F9 | Writes the board shown when you press it, with its defect boxes, to a picture file you choose (a run goes on while you name the file); the result itself is already recorded. Each picture saved is recorded in the audit trail with who saved it, which result it shows and where it went |

A button and its key do the same. The key works whichever control on the Inspection page is selected (the defect
list, the View box, a button), and only while that page is shown. Both go grey while the action is not possible:
Start and Next Board until images are queued, while no board model is chosen in the top bar (with none yet, the page
says to ask an Engineer to create one), while a run is on and while a board is being inspected; Stop while no
run is on; Save Image… before the first result and while a picture is being saved. Every result is recorded as it
arrives, with the checks that decided it, before the next board starts; the records are on Logs & Export. If a result
cannot be recorded (the disk is full, the workspace folder cannot be written, another program holds the database) the
run stops with AOI-INSP-008: press Next Board to carry on, and inspect that board again later; such a board is not on
Logs & Export and, if NG, has no alarm. When the system refuses the path of a result's files as too long, the run
stops with AOI-INSP-014 instead: ask an Admin to copy the workspace folder's contents into a folder with a shorter
path. An NG board that is recorded always has its NG alarm (AOI-INSP-003). Closing the
app while a board is being inspected asks whether to stop: No keeps the app open; Yes records the board in hand and
closes.
A run belongs to the board model it was started under. If the board model in the header changes during a run, the run
stops after the board in hand, which is saved under the run's board model, and the status bar and the alarm log say so
with AOI-INSP-012; the remaining boards are not inspected. Check the board model in the header, then press Start to
carry on with the queue. The board shown before the change is cleared, so "Compare with Golden board ›" never opens it
as a board of the new board model. The board in hand, from Start or Next Board, is cleared too when its result arrives:
the line under the banner names it, its verdict and the board model it was saved under, until the next board, and its
record is on Logs & Export when it was saved (a failed save shows AOI-INSP-008); in a run with boards left, the line
also says to press Start to carry on with the queue. "Compare with Golden board ›" is grey while there is no result to open: before the first
board, after a board that was not inspected and after a board model change.
A run also belongs to the user who pressed Start. If another user signs in with Switch User during a run, the run stops
after the board in hand, which is recorded under the user who pressed Start, and the status bar says so; the user now
signed in presses Start to carry on with the queue, and those boards are recorded under their name.
Each board is judged with the AI model, recipe, scale and Golden board in use when it starts. If an Engineer trains or
activates an AI model version, saves a recipe, sets a scale or sets a Golden board while the Inspection page is open,
the next board
uses it, whether you press Next Board or Start or load a new queue. During a run, the board in hand finishes with what it
started with and the boards after it use the new one; the line under the banner and the alarm log say so with
AOI-INSP-013. Each record names the AI model version active when its board was judged, the recipe revision that
judged it (which says whether the AI check ran) and the Golden board it was judged against. When the recipe turns the
AI check off, no AI model judges the boards, so an AI model version activated during a run changes nothing that judges
them and the run goes on with no AOI-INSP-013 (the boards after it name the version now active); a saved recipe or a
Golden board set still moves the run, and a training run does too, as it sets a new Golden board, and the line then
says the AI check was off in place of naming an AI model.
A scale set changes nothing that judges a board while the recipe holds its sizes in px, so the run then goes on with no
AOI-INSP-013.

Reading the verdict: while a board is being inspected the banner turns grey and reads "Inspecting…", and the status
bar at the bottom names the board and its place in the queue, such as "Inspecting board_07.png (3 of 12)…". The
verdict then fills the banner: ✓ OK on green, ✗ NG on red, ▲ WARN on amber, with the defect list under it (section 3),
and the status bar shows the board's summary line: file, AI score, defects and time.
A board the app cannot read stops the run with a message that says what happened and what to do; the banner then reads
"· Not inspected" on grey, the picture and the defect list are empty, and the view names the board, the error's code
and what happened, so the verdict of the board before is never shown beside it. Press Next Board to go on with the
queue; when it was the last board, the view says so and offers Load Images… to queue more. A board is never passed on
no evidence: the run stops the
same way when the Golden board's file is gone or damaged (AOI-INSP-009), when nothing can judge the board because the
board model has neither a Golden board nor an AI model yet, or the recipe turns both off (AOI-INSP-010), and for a
picture under 11 px on a side (AOI-INSP-011); for the first two, call an Engineer. At the end of the queue the status bar reads "End of
queue".

## 3. When a board is NG or WARN

The defect list under the banner names each defect with its number, type, score, side and position; click a row to
zoom the picture to it. Press "Compare with Golden board ›" (or open Compare from the sidebar and press Use Last
Inspected) to see the board as it was judged, lined up with the Golden board it was judged against, and the decision table that
produced the verdict: every check with its source, value, threshold, rule and result, the failing rows in red or amber,
exactly as they were decided and stored; the board is not inspected again. The Show menu picks the view: Side by side
shows the Golden board, with a dashed box per defect, beside the board with its labelled defect boxes; Difference
heatmap and AI score heatmap show the board under its map; Defect boxes only hides the Golden board and fits the board
with its boxes to the width of both panes. Any other view brings the Golden board back and fits the board to its half
again; a zoom is reset at either switch. The view stays as chosen for Test Image… and a pane's Re-evaluate ›, while
"Compare with Golden board ›", Use Last Inspected, Golden Board and Reference… ask for a Golden board, so they show it
in Side by side. The "why" box under the table explains the verdict in plain words, under the heading "Why this board is
NG:": one sentence per failing check, the NG ones first, naming the check, its value and its threshold with their unit
("The changed area is 2.35 % of the board, at or above its threshold of 0.50 %."; an ROI's value is a multiple of the AI
score threshold, "2.00 ×": the recipe's when an Engineer sets one, otherwise the AI model's). With no failing check it
says that every check that decides the verdict is inside its threshold or, for a WARN, that defects above Minor severity
are marked on the board, so a person needs to look. A sentence for each check that did not run (no Golden board set, no
AI model trained, or the AI check turned off in the recipe) says what to do. On a result opened from its record, with
"Compare with Golden board ›" or Use Last Inspected even right after the board was inspected, it says what was set when
the board was inspected ("No AI model was trained for this board model when the board was inspected, …"), not what is
set today. The Inspection page shows today's sentence under its summary, and so does Compare for a board it inspects
itself, with Test Image…, Golden Board, Reference… or a pane's Re-evaluate ›. A line under the verdict says when the
result was judged, which AI model version was active and which recipe revision judged it; when the recipe turned the AI
check off, the "why" box says that no AI model judged the board. When an Engineer has changed either since, the line
says so, and the table still shows the thresholds that applied at the time. When the result's heatmaps are no longer
stored (OK results lose them after the retention period), the line says so with the code AOI-CMP-001, and the Side by
side and Defect boxes only views still work. When the stored picture itself was deleted, or cannot be read (a message
with AOI-CMP-006 names the file), the page says "Board picture no longer stored", the table still stands, and
Re-evaluate › there inspects the board again from its image file. The Golden board pane names the file the result was
judged against. When that file has changed, cannot be read or is gone, or the result names none (it was judged without
one, or saved before this version), the pane says "Golden board not available" and why, rather than show today's Golden
board, and Re-evaluate › under it inspects the board again with today's Golden board, or without one while the board
model has none, as the pane then says; the line under the verdict names today's when an Engineer or a training run has
set another. A long file name over a picture, in a message on its pane or in the line under the verdict wraps onto the
next line after a _ or -. The thresholds panel, "Try other thresholds", is for Engineers and is not shown to an
Operator: every board Compare inspects for you is judged by the board model's recipe, and a board left on Compare that
was inspected with values the recipe does not hold when you sign in (an Engineer's thresholds not saved, a recipe
revision saved since, or a scale set since that gives a size in mm other px; values that did not judge the board, such
as the AI score threshold when its AI check did not
run, are not counted) is cleared when you sign in, on any page, and inspected again by the recipe once Compare is shown,
so you never see the verdict those values gave.

## 4. Alarms and messages

(to be written: the alarm log, error codes and what to do)

## 5. End of shift

**History.** Logs & Export lists the boards inspected, newest first, from the last 7 days: every operator's, so the
next shift sees the line's history. Narrow it with **From** and **To**, **Board model**, **Operator** and **Result**
(All, OK, NG or WARN), then press **Filter**; the filters combine. Tick **Include archived** for records older than the
retention (30 days unless an Admin changed it): they are archived, not deleted, and stay searchable. A click on a
column's header sorts by it. Select a row to see its overlay beside the table, and press **Open in Compare ›** (or
Enter, or double-click the row) to see that board on Compare as it was decided, its failing checks marked. The line
under the table counts the listed records by verdict. Only an Admin deletes records, with a reason the audit trail
keeps.

(to be written: handing over)
