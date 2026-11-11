# Trying the app: a guide for testers

For anyone asked to try AOI PoC Inspector on their own Windows PC, with no technical knowledge needed. The demo
takes about 20 minutes; training it on your own boards (section 7) about an hour. Words in **bold** are what the
app's own buttons and pages say.

This is an internal test build. Use it on your own PC only, never on a customer's PC or in front of a customer
([install.md](install.md)).

## 1. What you need

- A Windows 10 (version 21H2 or newer) or Windows 11 PC (64-bit), and the right to install programs on it (Windows asks for an administrator
  when you install).
- About 1 GB of free disk space.
- The setup file, named like `AOI-PoC-Inspector-0.4.0.dev0-setup-x64-pilot-signed.exe`. Ask the person who asked you
  to test for it. If you have a GitHub account, you can get it yourself: see "Getting the setup file yourself" at the
  end of this page.

No Python, internet connection or camera is needed.

## 2. Install it

1. Double-click the setup file.
2. Windows may show a blue box, **Windows protected your PC**. This is expected: the test build is not signed the way
   Windows recognizes. Click **More info**, then **Run anyway**.
3. Windows asks **Do you want to allow this app to make changes to your device?** and shows *Publisher: Unknown*.
   Click **Yes**.
4. The setup window says it is a pilot build (or, for an unsigned build, an internal test build). Click **Next** on
   each page (keep the folder it offers; the desktop shortcut box is optional), then **Install**, then **Finish**.

## 3. Open the demo

1. Open the Windows Start menu and type `AOI`.
2. Click **AOI PoC Inspector (Demo)**. The demo opens in a minute or less, with a yellow **Demo** badge at the top left,
   already signed in. Nothing you do in the demo touches anything else.

The demo comes with one board type (`DEMO-TBOX-A1`), an AI model already trained for it, and ten board pictures ready to
inspect. The pictures are drawn by a program, not photographed, so they show how the app works, not how well it finds
real defects.

## 4. Try these steps and tick each one

| # | Do this | You should see | Worked? |
|---|---|---|---|
| 1 | Look at **Home** | The line "Stage 1 workflow: upload → train → validate → inspect" and six cards under it | ☐ |
| 2 | Click **Inspection** on the left | "10 demo board(s) queued" at the top right | ☐ |
| 3 | Press **Start** (or the F5 key) | Boards appear one by one, each marked ✓ OK on green | ☐ |
| 4 | Wait | The run stops by itself on the fourth board, `board_04.png`, marked ✗ NG on red, with a box around the defect | ☐ |
| 5 | Press **Compare with Golden board ›** | The good board on the left, board 4 on the right, the same place boxed on both, and a box under the verdict, "Why this board is NG:", in plain words | ☐ |
| 6 | Click **Inspection** and press **Start** again | The last six boards come out ✓ OK and the bottom line says "End of queue" | ☐ |
| 7 | Click **Logs & Export** | All 10 boards listed: 9 OK and 1 NG. Clicking the NG row shows its picture | ☐ |
| 8 | Press **Export CSV**, press **Yes**, and save on your Desktop | Two files you can open in Excel: the one without `_checks` in its name has one line per board | ☐ |

### Inspect your own pictures

| # | Do this | You should see | Worked? |
|---|---|---|---|
| 9 | On **Inspection**, press **Load Images…** and pick one or more board photos (PNG, JPG, BMP or TIFF), then **Start** | Each picture gets a verdict, OK, NG or WARN, with the time it took | ☐ |
| 10 | Press **Load Folder…** and pick a folder of pictures, then **Start** | Every picture in the folder is queued and judged | ☐ |

No board photos? The demo's own pictures are in the folder `AOI_Workspace-Demo\demo-boards` in your user folder
(type `%USERPROFILE%\AOI_Workspace-Demo\demo-boards` in File Explorer's address bar).

**What to expect with your own photos in the demo.** The demo's AI model learned only the drawn demo board, so a photo
of any other board will be called NG or WARN almost every time. That is expected and is not a fault to report. To have
your own boards judged, train the app on them: section 7.

### Start over

**Settings** on the left, then **Reset Demo**, then **Yes**, puts the ten boards back as they were. It also clears
the demo's records, so if something went wrong, send them first (section 5).

## 5. If something goes wrong

- Every error window starts with a code such as `AOI-INSP-016`, says what happened and what to do. Press
  **Show Details…**, then take a screenshot (Windows key + Shift + S) and send it with a sentence about what you
  clicked just before.
- If a step in the table did not do what it says, write down its number and what you saw instead.
- The app keeps its own records in `%USERPROFILE%\AOI_Workspace-Demo\logs`. If asked, zip that folder and send it.
- If the app closed by itself, start it again from the Start menu: it reopens the demo where it was.

## 6. Remove it

Windows **Settings → Apps → Installed apps**, find **AOI PoC Inspector**, click **…** and **Uninstall**. This removes
the program only. To remove the demo's files too, delete the folders `AOI_Workspace` and `AOI_Workspace-Demo` from
your user folder.

## 7. Train it on your own boards

The demo judges only its own drawn board. To try the app on your boards, give it photos of them and let it learn. It
takes about an hour, most of it the computer's.

**The photos.** What the app learns is what a good board looks like in your photos, so the photos matter more than
anything you set afterwards.

- **70 or more photos of good boards**, and **one or more photos of each defect** you want it to know. More good boards
  give a steadier result: 20 of them teach the AI model and the rest test it.
- One board type and one side of it, the **whole board in the picture**, taken by the **same camera from the same
  place**, straight above the board, in **the same light**. PNG, JPG, BMP or TIFF, up to 50 megapixels each.
- The app corrects a photo that is brighter, darker or tinted, a board that lies a little turned or shifted, and a
  photo of another size. It cannot correct a blurred photo, a reflection that hides a part, or a photo taken from
  another angle; and it says so, with WARN, when the light is more than a third off or more than a twentieth of the
  board is out of the picture.
- Put them in one folder with two folders in it: `ok`, with the good boards, and `ng`, with a folder for each defect
  named after it, such as `ng\Missing Component` or `ng\Solder Bridge`. Photos put straight into `ng` are asked for
  their defect when you pick the folder. Other files in the folders are passed over.

**The steps.** Open the Start menu, type `AOI` and click **AOI PoC Inspector** (not the Demo one). **Home** opens on
a guide of three steps.

| # | Do this | You should see | Worked? |
|---|---|---|---|
| 11 | Press **Choose the Admin's Password…**, type a password twice, then save or print the recovery code it shows | The guide's line about the password goes | ☐ |
| 12 | Type the board's name and your company's name, press **Create**, then **Save to File…** for the recovery key (on a USB drive, not this PC) and **I Have Saved the Key** | Step 1 is ticked and step 2, Images, opens | ☐ |
| 13 | Press **Pick Folder…** and pick your folder | "OK images: … of 70" and "NG images: … of 1" are ticked; "Not taken" counts any file that is not a photo, and **Show Why** names each | ☐ |
| 14 | Drag a box around the defect on each NG photo as it shows | After the last box, step 3, Train, opens | ☐ |
| 15 | Press **Train** | A line says the part in hand and the time left: about 15 minutes on a laptop for 100 photos. Other pages can be used meanwhile | ☐ |
| 16 | Read what the screen then says | "AI model v1.0 (Trial) judges … boards", and how the boards it kept apart came out: **Missed defects** and **False calls**, counted | ☐ |
| 17 | Press **Inspect a Board…**, pick photos the app has not seen, then **Start** | Each gets OK, NG or WARN. Press **Compare with Golden board ›** on one to see what each check measured | ☐ |

**What to expect.** "Trial" means one person labelled the photos and nobody checked them: it is a first look, not a
validation. A good first result has few false calls and no missed defect on the boards kept apart; with fewer than
about 100 good boards the counts are too small to say more than that.

- **If step 16 says a master sample was judged wrongly,** the app will not inspect boards until that is put right,
  on purpose: it found that it cannot tell one of your known-defective boards from a good one (or the other way
  round), and says which. Look at that photo first. Is it in the right folder? Can you see the defect in the photo at
  its full size? A defect a few pixels across is below what a photo of this size can show; photograph that area closer
  or with a higher-resolution camera. Otherwise it is a finding to send (section 5): an Engineer looks at the board on
  **Compare** and sets the recipe.
- **If many good boards come out WARN or NG,** press **Compare with Golden board ›** on one. The table under the
  pictures says which check failed. "Lighting change" or "Board in frame" means the photo, not the board. Send the
  rest as findings: say how the photos were taken.
- What these steps do is unchanged by the size of your trial, but what they prove is not: how well the app finds real
  defects is measured on the factory's own boards, at the factory's station, before any board is judged by it alone.

## Getting the setup file yourself

This needs a free GitHub account: GitHub lets only signed-in users download build files.

1. Sign in to GitHub and open <https://github.com/jdseo921/pcb-aoi-monitor/actions/workflows/build.yml>.
2. Click the newest run with a green tick whose branch is `main`.
3. Scroll to **Artifacts** and click the one ending in `-windows-x64-pilot-signed-installer` (or `-unsigned-installer`
   for a build of another branch). A zip file downloads.
4. Right-click the zip, **Extract All…**, and open the folder: the setup file is inside.

Build files are kept for 30 days; if none is listed, ask for a new build.
