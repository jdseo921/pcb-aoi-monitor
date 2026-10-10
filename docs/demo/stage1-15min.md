# Stage 1 demo: 15 minutes

The 5-minute script, then the three things a customer asks next: how do you check it, how does it learn our boards,
and who decides the thresholds. Live training takes 2 minutes at most. Rehearse it on the demo laptop first
([README.md](README.md), "Before every demo").

Ready before they sit down: as for the 5-minute script, the demo workspace reset, at **Home**, **Presenter theme** on.

## 0:00 to 3:45, the 5-minute script up to the report

Follow [stage1-5min.md](stage1-5min.md) from "0:00 to 0:45, Home" to the end of "3:15 to 3:45, finish the run": the
run of 10 boards, the NG board, **Compare**, and the run finished. Keep the report for the end.

## 3:45 to 6:00, check it on boards with known defects

1. Click **AI Model Test**. **Source** reads "DS-DEMOTBOXA1-R1-TOP-v1: its locked validation set, 31 images".

> "Before training, we set 31 boards aside and locked them: the AI model never sees them. 11 of them have a known
> defect. We check every AI model on them before anyone uses it."

2. Press **Run Test**. It takes a few seconds. The tiles fill: **Missed defects** 0 of 11, **False calls** 1 of 20,
   then **Recall**, **Precision** and **Accuracy**.

> "Two numbers matter on the line: defects it let through, here none of 11, and good boards it stopped, here 1 of 20.
> Always as counts. The small line under each count is the worst case those counts still allow: with 11 defective
> boards we cannot promise more than that, so on your boards we ask for enough samples to make it small. These boards
> are drawn, so these counts say nothing about your boards; they show what you will get on yours."

3. Select the red row in the table: the one good board it stopped. Its picture shows beside the table.

Speak about missed defects and false calls; do not lead with **Accuracy**.

## 6:00 to 9:30, train live

1. Click **Training**. Under **Self-training**: **Dataset version** DS-DEMOTBOXA1-R1-TOP-v1, and the line
   "Validation set locked ✓ 20 OK / 11 NG · training set 40 OK, 3 NG". Leave **Epochs** at 60 and **Network input
   size** at 256.
2. Press **Start Training**. The bar moves and the line under it reads, for example, "Training epoch 7 of 60 · 15 % ·
   about 1 min left". On our 4-core test PC it took 98 s.

> "It learns what a good board looks like from 40 photos of good boards. The 3 NG photos only set where the threshold
> sits. Training runs in the background: the line keeps inspecting meanwhile."

If the line says more than 2 minutes are left, press **Cancel** and say "here is one trained on the same boards
earlier": AI model v1.0 is already there, and nothing is lost.

3. When it ends, the status bar reads "AI model v1.1 trained: select it and press Activate Selected to judge boards
   with it". Under **AI model versions**, v1.1 is listed over v1.0, and v1.0 still has the dot in **Active**.

> "A new AI model never takes over by itself. An engineer checks it on the locked boards and switches it on."

4. Select the v1.1 row and press **AI Model Card**: what it was trained on and its thresholds. Its first line reads
   "Not yet tested on a locked validation set: nothing on this card is a measure of accuracy."
5. Press **Activate Selected**: the dot moves to v1.1. Then press **Roll Back** (it reads "Roll Back to v1.0"): the
   dot moves back.

> "Switching on and going back are one click each, and both are recorded with who did it."

## 9:30 to 12:30, who decides the thresholds

1. Click **Logs & Export**, select the NG row of `board_04.png` and press **Open in Compare ›**. It opens as it was
   judged, with the table and "Why this board is NG:".
2. In "Try other thresholds (nothing is saved until you press Save to Recipe)", set **Allowed difference regions** to 2
   and press **Re-evaluate**. The line beside it reads "Would be: ✗ NG".

> "Say your engineers allow two small differences. This board is still NG, because the AI model finds the missing part
> on its own. Two independent checks: loosening one does not let a missing part through."

3. Point at **Save to Recipe**, and do not press it.

> "Nothing changes until an engineer saves it, with a reason. Every saved change is a new recipe revision, and the old
> one can be restored."

If it was pressed by mistake, carry on: **Reset Demo** after the demo puts the recipe back.

## 12:30 to 14:30, the report they keep

Follow "3:45 to 4:45, the report they keep" in [stage1-5min.md](stage1-5min.md): **Logs & Export**, **Export CSV**,
**Export Image Overlays**, and hand them the USB stick.

## 14:30 to 15:00, the next step

> "Next, we do this with your boards: you send photos of good boards and of boards with known defects. We train on your
> good boards, check on your defective ones, and show you the counts. Nothing leaves your site unless you agree."

Give them [for-clients.md](for-clients.md).

## With the customer's images

When the customer sent photos before the meeting, an engineer prepares their board model the day before, following
the engineer manual ([engineer.md](../manual/engineer.md)): their good and defective photos as samples, frozen as a
dataset version with their defective boards held back as its locked validation set. In the room, pick their
board model in the header and follow the same steps; **Start Training** may take longer on more photos, so rehearse
it and use the 2-minute rule above. Never show one customer's boards to another.

## After they leave

**Exit presenter theme**, then **Settings**, **Reset Demo**, and confirm. Then switch the **Presenter theme** on again
for the next demo: a reset brings the demo back as it was installed, with the theme off.
