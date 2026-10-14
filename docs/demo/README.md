# Stage 1 demo kit

For whoever shows the app to a customer (REQ-SET-007, REQ-SET-008, REQ-SET-009; Customers & Launch, "Demos"). Each
script says what to click and what to say, minute by minute. Names in bold are the app's own buttons and pages.

| Script | Length | Use it for |
|---|---|---|
| [stage1-5min.md](stage1-5min.md) | 5 minutes | Every first meeting. It must never go wrong, so rehearse it before every demo |
| [stage1-15min.md](stage1-15min.md) | 15 minutes | The 5-minute script, then training on the customer's OK images, checking on their NG samples, and a threshold tuned live |
| [stage1-45min.md](stage1-45min.md) | 45 minutes | The 15-minute script, then recipes, AI model versions and how their data is handled |
| [for-customers.md](for-customers.md) | 1 page | The customer's handout: what they saw, what Stage 1 needs from them, and what they keep |

Korean drafts of each file are in [ko/](ko/), marked for review by a native speaker before they go to a customer.

## Ground rules

- Demo the release build only: a signed installer from a tagged commit, never a developer setup. None exists
  yet (the code-signing certificate, plan item J6): today's unsigned installer is for rehearsing on our own PCs,
  never for a customer's room ([install.md](../install/install.md)).
- Lead with an NG board and open **Compare**. Show Settings only if asked.
- Show only finished features. The presenter theme hides 3D Profile, and the Stage 2 to 4 hardware on **Settings**,
  for this reason. Settings stays in the sidebar for the Admin role alone, for **Reset Demo**.
- Live training runs 2 minutes at most. AI model v1.0 is already trained, so nothing waits on training.
- Use the customer's images whenever we have them. The 10 demo boards are drawn by the app's own tool: they show
  how the app works, never how well it finds defects. Never quote a number from them as accuracy, and never say
  "99.9 %": every claim names its counts ("found 14 of 14 NG samples, called 1 of 60 OK samples NG", from their
  boards).
- End every demo with a report the customer keeps: the CSV of results and the pictures with their defect boxes,
  on a USB stick.

## Before every demo

Rehearse once on the demo laptop, the day before or in the room, and tick each line:

- [ ] The release build is installed. Note its version: the line under **Settings** shows it, and so does the title
      bar outside the presenter theme.
- [ ] The demo workspace is reset: start `AOI PoC Inspector (Demo)` from the Start menu (it opens signed in as
      `admin`, at **Home** after a normal close). Open **Settings**, press **Reset Demo** and confirm; the presenter
      theme, if it is on, stays on. Leave it at **Home** with the **Presenter theme** on.
- [ ] Wi-Fi is off. The app needs no network ([ports.md](../install/ports.md)).
- [ ] The projector is checked at 1920 × 1080 and at 1366 × 768: every page of the script reads from the back row.
      Every page and tab the scripts open fits 1366 × 768, its verdict, defect boxes and the table on **Compare** in
      view with nothing scrolled; where the app has under 900 px of height or 1400 px of width, the presenter theme's
      text is 16 pt, not 18 ([screen sizes](../tests/2026-10-screen-sizes.md)). The presenter theme fills the whole
      screen, with no title bar or taskbar; **Exit presenter theme** brings them back. Those sizes were measured on
      Linux at 1366 × 768, not on a Windows projector, so check on the projector that **Start** on **Inspection** and
      the last row of the table on **Compare** are in view. On a projector that takes less than 1366 × 768, play the
      recording.
- [ ] The projector is connected, at the resolution it will run at, before the app starts, and Windows shows the
      same picture on both screens (Win+P, "Duplicate") or on the projector alone ("Second screen only"). Full screen
      has no title bar to drag the app from the laptop's screen to the projector's.
- [ ] You have tried the way out: Alt+F4 closes the app, as it closes any app. Signed in below the Admin, you leave the
      presenter theme by signing in as `admin` with **Switch User**, then pressing **Exit presenter theme**.
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
| The app closes by itself | Start `AOI PoC Inspector (Demo)` from the Start menu: it opens the demo workspace again on the page it showed (after you close it yourself, at **Home**), signed in as `admin`, in the theme it had, in under 30 s. Say "let me open that again" and carry on from the last step; if you were showing the Operator view, sign in as `operator` again with **Switch User** first |
| Training is slow | If the time left reads over 2 minutes, press **Cancel** and use AI model v1.0, which is already trained: "here is one trained on the same boards earlier". Nothing is lost |
| A verdict looks wrong | Open **Compare**: the table shows each check, its value and its threshold, and the box under it says why in plain words. Explain it from there; never guess |
| A message appears | Read it out: it says what happened and what to do, with a code. Do what it says, then carry on. Its Show Details button holds technical words for support: leave it closed in front of the customer |
| The demo goes off course: a wrong click, a board run twice | Start again from a clean demo without leaving the presenter theme, three clicks from any page: **Settings** in the sidebar, **Reset Demo**, then Yes. The demo comes back as installed, at **Home**, in under 10 s once any work still running has stopped (an AI model test finishes its folder first); click **Inspection** and press **Start** to run the boards again. Signed in as `operator`, press **Switch User** and sign in as `admin` first, as Settings is the Admin's |
| The presenter theme is in the way, or you need a page it hides | Signed in as `admin`, press **Exit presenter theme** in the header, on any page: one click. Turn it on again with **Presenter theme** on **Settings** |
| The app is started again while it is open | The app already open comes to the front, as it was; nothing is lost and nothing restarts. If a message says the app is already open instead, press OK and switch to it on the taskbar |
| No projector | Play the recording, and hand over the report as usual |

## After the demo

1. Hand over the USB stick with the report (the 5-minute script ends with it).
2. Open **Settings** and press **Reset Demo**, so the next demo starts clean. The presenter theme stays as it is.
3. Delete the customer's images from the laptop unless they agreed in writing that we keep them, and note what we
   keep and for how long.
4. Write down their questions and what they asked to see next: it goes into the Stage 1 trial plan.

## Why the scripts are trusted

`tests/test_demo_scripts.py` clicks through the 5-, 15- and 45-minute scripts in the presenter theme on every pull
request from **Load Demo Workspace** on, the 5- and 45-minute ones to **Reset Demo**, the 5-minute one on a 1920 × 1080
and on a 1366 × 768 screen, and goes red on any dialog or message on the way that the script does not answer itself, or
on a page wider than a 1920 px screen. It also starts the demo as the Start menu's Demo entry does, ends it mid-run by a
crash and again by closing it, starts it again, and checks that it opens as "When something goes wrong" says: the demo
workspace, signed in as `admin`, in the theme it had, in under 30 s, with no dialog. It also checks that every name in
bold in these files is a real button or page, that the text uses the Charter's words, and that each file has its Korean
draft. `tests/test_demo_fit.py` opens every page and tab the scripts show at 1366 × 768, in the presenter theme and in
the dark one, and goes red on a page or a panel of fields that scrolls sideways, a line of text cut off, or a verdict,
defect box or table row on **Compare** that is not in view. Customers & Launch also asks that someone in each reader's
role follows the scripts on the release build before they go out; that has not been done yet, as the release build does
not exist.
