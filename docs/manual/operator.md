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
the workspace folder cannot be written) the run stops with AOI-INSP-008: press Next Board to carry on, and inspect that
board again later.

Reading the verdict: while a board is being inspected the banner turns grey and reads "Inspecting…", and the status
bar at the bottom names the board and its place in the queue, such as "Inspecting board_07.png (3 of 12)…". The
verdict then fills the banner: ✓ OK on green, ✗ NG on red, ▲ WARN on amber, with the defect list under it (section 3),
and the status bar shows the board's summary line: file, AI score, defects and time.
A board the app cannot read stops the run with a message that says what happened and what to do, and the banner keeps
the last verdict; press Next Board to go on with the queue. At the end of the queue the status bar reads "End of
queue".

## 3. When a board is NG or WARN

(to be written: the defect list, opening Compare in one click, what the explanation means)

## 4. Alarms and messages

(to be written: the alarm log, error codes and what to do)

## 5. End of shift

(to be written: history and export, handing over)
