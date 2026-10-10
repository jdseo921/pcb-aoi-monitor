# Stage 1 demo: 45 minutes

For an engineering team that will own the station. The 15-minute script, then recipes, AI model versions, how their
data is handled, and who may do what. Rehearse it on the demo laptop first ([README.md](README.md), "Before every
demo"); each part below can be dropped if time runs short, the report never.

Ready before they sit down: as for the 5-minute script, the demo workspace reset, at **Home**, **Presenter theme** on.

## 0:00 to 12:30, the 15-minute script up to the report

Follow [stage1-15min.md](stage1-15min.md) to the end of "9:30 to 12:30, who decides the thresholds": the run, the NG
board on **Compare**, the check on the locked boards, training live, and a threshold tried and not saved.

## 12:30 to 20:00, recipes

1. Click **Recipe Editor**. The board model DEMO-TBOX-A1 is picked in the header.
2. **Thresholds** tab: every check's threshold, with its unit. These are the numbers **Compare** showed in its table.

> "A recipe is the set of thresholds for one board model. Your engineers own it."

3. **ROIs** tab: a region of the board with its own threshold, for a part that needs a closer look. Show
   **Draw ROI** if they ask, then leave without saving.
4. **AOI checks** tab: the checklist of what the station checks for this board model, each with the reason it is on or
   off.
5. **Revisions** tab: every saved recipe, who saved it, when and why. **Restore as New Revision** brings an old one
   back without deleting anything.

> "Nothing is overwritten. Every board's record names the recipe revision that judged it, so a verdict from last
> month can be explained with the thresholds of last month."

## 20:00 to 28:00, AI model versions

1. Click **Training**. Under **AI model versions**: v1.1 from the live training, and v1.0, active.
2. Select v1.1 and press **AI Model Card**: what it was trained on, the dataset version and its thresholds. Its first
   line says it is not yet tested on a locked validation set, so the card claims no result.
3. Press **Activate Selected** to make v1.1 active. Click **AI Model Test** and press **Run Test** again: the tiles show
   v1.1's counts on the same 31 locked boards.
4. Open the **History** tab: both runs are there, newest first. Select a row to see it again.

> "Before a new AI model judges your boards, it is tested on the same locked boards as the one before, and you compare
> the counts. Every run is kept."

5. Click **Training** and press **Roll Back** (it reads "Roll Back to v1.0"): v1.0 is active again.

## 28:00 to 36:00, their data

Talk to it with **Training** open on its **Datasets** tab, which lists the frozen dataset versions.

- Their images stay on the station PC, in its workspace folder. The app opens no network port and makes no connection;
  it runs with the network cable out ([ports.md](../install/ports.md)).
- Training images are kept in an encrypted store for their company, whose key is held by Windows on that PC.
- A dataset version is frozen: the exact images and labels an AI model was trained on, who labelled each image and
  who checked the label. Its validation set is locked, so an AI model is never tested on the images it learned from.
- Every record keeps its verdict, the checks that decided it, the AI model and the recipe revision. Records older than
  30 days are archived, not deleted, and stay searchable: on **Logs & Export**, tick **Include archived** and press
  **Filter**.
- Only an Admin deletes records, with a reason that the audit trail keeps.

If they ask to see the settings: **Exit presenter theme**, open **Settings**, show **Dataset stores**, then switch the
**Presenter theme** on again.

## 36:00 to 40:00, who may do what

1. Press **Switch User**, pick `operator (Operator)` and press OK.

> "An Operator runs boards and looks at results. Training, AI Model Test and the Recipe Editor are greyed: an Operator
> cannot change what judges a board."

2. Click **Inspection** to show the Operator's page, then press **Switch User** and pick `admin (Admin)` again. Only an
   Admin sees **Exit presenter theme**, so never end the demo signed in as the Operator.

## 40:00 to 43:00, the report they keep

Follow "3:45 to 4:45, the report they keep" in [stage1-5min.md](stage1-5min.md): **Logs & Export**, **Export CSV**,
**Export Image Overlays**, and hand them the USB stick.

## 43:00 to 45:00, the next step

> "For Stage 1 with your boards we need photos of good boards and of boards with known defects, your defect types, and
> an hour with an engineer of yours to check the labels. We then come back with this demo on your own boards, and the
> counts."

Give them [for-clients.md](for-clients.md), and write down what they asked to see next.

## After they leave

**Exit presenter theme**, then **Settings**, **Reset Demo**, and confirm: it removes v1.1, the runs on AI Model
Test and the records. Switch the **Presenter theme** on again for the next demo.
