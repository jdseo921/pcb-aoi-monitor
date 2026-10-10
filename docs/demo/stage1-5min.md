# Stage 1 demo: 5 minutes

The first meeting. One run of 10 boards, one NG, **Compare** shows why, and the customer keeps the report. This
script must never go wrong: rehearse it before every demo ([README.md](README.md), "Before every demo").

Ready before they sit down: the demo laptop on the projector, the app open in the demo workspace (the yellow
**Demo** badge at the top left) at **Home**, the **Presenter theme** on, signed in as `admin`, and an empty USB stick
with their name on it.

## 0:00 to 0:45, Home

Point at the line "Stage 1 workflow: upload → train → validate → inspect" and its six cards.

> "This is an inspection station for your boards. In Stage 1 you send us photos of your boards: we teach the AI model
> what a good board looks like, check it on boards with known defects, then inspect. Today's 10 boards are drawn by our
> own tool, so they show how it works, not how well it finds defects. That we measure on your boards."

## 0:45 to 1:30, a run with one NG board

1. Click **Inspection** in the sidebar. The top right says 10 demo boards are queued, 3 s per board.
2. Press **Start** (F5). Boards appear one after another, each with ✓ OK on green.
3. The run stops by itself at the fourth board, `board_04.png`: ✗ NG on red, its defect boxed on the board and
   listed under the verdict, and the line "Paused at the NG board board_04.png".

> "Every board gets a verdict, OK or NG, and the time it took is on the line under the verdict. When a board is NG the
> run stops, so a person looks at it before the next one."

## 1:30 to 3:15, Compare shows why

1. Press **Compare with Golden board ›**.
2. Left: the Golden board, the good board every board is compared with. Right: `board_04.png`, with the same place
   boxed on both. A component is missing.

> "Here is the good board, and here is this one. The box shows where they differ: a part is missing."

3. Point at the table on the right: each check, its value, its threshold and its rule. The rows in red decided the
   verdict: **Difference regions** (2, where 0 are allowed) and **AI score** (about 8, where under 5 is OK).
4. Point at the box under it, "Why this board is NG:", which says the same in plain words.

> "Nothing is hidden: every verdict shows which checks decided it, with numbers, and says why in plain words. Your
> engineers set every threshold, and every change is recorded."

If they ask about the heatmap, pick **Difference heatmap** in **Show:**, then **Side by side** again.

## 3:15 to 3:45, finish the run

Click **Inspection** and press **Start**. The six boards left come out ✓ OK, and the status bar reads "End of queue".

## 3:45 to 4:45, the report they keep

1. Click **Logs & Export**. The 10 boards are listed, newest first, and the line under the table counts them:
   9 OK, 1 NG. Select the NG row: its picture with its box shows beside the table.
2. Put their USB stick in. Press **Export CSV**, confirm, and save the file on the stick under their company's name.
3. Press **Export Image Overlays**, confirm, and pick the stick. The pictures of the 10 boards, with their boxes, are
   copied there.
4. Hand them the stick.

> "This is yours: every result with its time, the AI model and the settings that judged it, and the pictures. Every
> export is recorded too, with who made it."

## 4:45 to 5:00, the next step

> "Next, we do the same with your boards. Send us photos of good boards and a few with known defects, and we show you,
> on your own boards, how many defects it found and how many good boards it stopped, with the counts."

Give them [for-clients.md](for-clients.md).

## After they leave

**Exit presenter theme**, then **Settings**, **Reset Demo**, and confirm: the demo is ready for the next time.
