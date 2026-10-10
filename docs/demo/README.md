# Stage 1 demo kit

For whoever shows the app to a customer (REQ-SET-007, REQ-SET-008, REQ-SET-009; Customers & Launch, "Demos"). Each
script says what to click and what to say, minute by minute. Names in bold are the app's own buttons and pages.

| Script | Length | Use it for |
|---|---|---|
| [stage1-5min.md](stage1-5min.md) | 5 minutes | Every first meeting. It must never go wrong, so rehearse it before every demo |
| [stage1-15min.md](stage1-15min.md) | 15 minutes | The 5-minute script, then training on the customer's OK images, checking on their NG samples, and a threshold tuned live |
| [stage1-45min.md](stage1-45min.md) | 45 minutes | The 15-minute script, then recipes, AI model versions and how their data is handled |
| [for-clients.md](for-clients.md) | 1 page | The customer's handout: what they saw, what Stage 1 needs from them, and what they keep |

Korean drafts of each file are in [ko/](ko/), marked for review by a native speaker before they go to a customer.

## Ground rules

- Demo the release build only: a signed installer from a tagged commit, never a developer setup. None exists
  yet (the code-signing certificate, plan item J6): today's unsigned installer is for rehearsing on our own PCs,
  never for a customer's room ([install.md](../install/install.md)).
- Lead with an NG board and open **Compare**. Show Settings only if asked.
- Show only finished features. The presenter theme hides Settings and 3D Profile for this reason.
- Live training runs 2 minutes at most. AI model v1.0 is already trained, so nothing waits on training.
- Use the customer's images whenever we have them. The 10 demo boards are drawn by the app's own tool: they show
  how the app works, never how well it finds defects. Never quote a number from them as accuracy, and never say
  "99.9 %": every claim names its counts ("found 14 of 14 NG samples, called 1 of 60 OK samples NG", from their
  boards).
- End every demo with a report the customer keeps: the CSV of results and the pictures with their defect boxes,
  on a USB stick.

## Before every demo

Rehearse once on the demo laptop, the day before or in the room, and tick each line:

- [ ] The release build is installed. Note its version: the title bar and the line under **Settings** show it.
- [ ] The demo workspace is reset: start `AOI PoC Inspector (Demo)` from the Start menu, open **Settings**, press
      **Reset Demo** and confirm. Leave it at **Home** with the **Presenter theme** on.
- [ ] Wi-Fi is off. The app needs no network ([ports.md](../install/ports.md)).
- [ ] The projector is checked at 1920 × 1080 and at 1366 × 768: every page of the script reads from the back row.
      The pages need a screen 1920 × 1080 or larger (the app needs at least 1888 × 907 px in the presenter theme);
      at 1366 × 768 they do not fit yet (#104). On a projector that takes only 1366 × 768, play the recording.
- [ ] The **Presenter theme** is on (**Settings**, then **Presenter theme**).
- [ ] Windows notifications are off (Focus or Do not disturb), and no other app is open.
- [ ] Only this customer's data is on the laptop: no other customer's images, reports or names, in the app, on the
      desktop or in recent files.
- [ ] A recording of the 5-minute script is on the laptop and on a USB stick.
- [ ] An empty USB stick for the customer's report, labelled with their name.
- [ ] The 5-minute script has run once from end to end, then **Reset Demo** again.

## When something goes wrong

| What happens | What to do |
|---|---|
| The app closes | Start `AOI PoC Inspector (Demo)` from the Start menu: it opens the demo workspace again, in the theme it had, in under 30 s. Say "let me open that again" and carry on from the last step |
| Training is slow | If the time left reads over 2 minutes, press **Cancel** and use AI model v1.0, which is already trained: "here is one trained on the same boards earlier". Nothing is lost |
| A verdict looks wrong | Open **Compare**: the table shows each check, its value and its threshold, and the box under it says why in plain words. Explain it from there; never guess |
| A message appears | Read it out: it says what happened and what to do, with a code. Do what it says, then carry on |
| No projector | Play the recording, and hand over the report as usual |

## After the demo

1. Hand over the USB stick with the report (the 5-minute script ends with it).
2. **Exit presenter theme**, open **Settings** and press **Reset Demo**, so the next demo starts clean.
3. Delete the customer's images from the laptop unless they agreed in writing that we keep them, and note what we
   keep and for how long.
4. Write down their questions and what they asked to see next: it goes into the Stage 1 trial plan.

## Why the scripts are trusted

`tests/test_demo_scripts.py` clicks through the 5-minute and the 15-minute scripts in the presenter theme on every pull
request, from **Load Demo Workspace** to **Reset Demo**, and goes red on any message on the way, or on a page wider
than a 1920 px screen. The 45-minute script is not clicked through. It also checks that every name in
bold in these files is a real button or page, that the text uses the Charter's words, and that each file has its
Korean draft. Customers & Launch also asks that someone in each reader's role follows the scripts on the release
build before they go out; that has not been done yet, as the release build does not exist.
