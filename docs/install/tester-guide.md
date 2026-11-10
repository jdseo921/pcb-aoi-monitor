# Trying the app: a guide for testers

For anyone asked to try AOI PoC Inspector on their own Windows PC, with no technical knowledge needed. It takes about
20 minutes. Words in **bold** are what the app's own buttons and pages say.

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

**What to expect with your own photos.** The demo's AI model learned only the drawn demo board, so a photo of any other
board will be called NG or WARN almost every time. That is expected and is not a fault to report. On real board photos
the app is known to flag good boards too often even after training on them; that is being worked on (issues #460 to
#462 on GitHub).

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

## Getting the setup file yourself

This needs a free GitHub account: GitHub lets only signed-in users download build files.

1. Sign in to GitHub and open <https://github.com/jdseo921/pcb-aoi-monitor/actions/workflows/build.yml>.
2. Click the newest run with a green tick whose branch is `main`.
3. Scroll to **Artifacts** and click the one ending in `-windows-x64-pilot-signed-installer` (or `-unsigned-installer`
   for a build of another branch). A zip file downloads.
4. Right-click the zip, **Extract All…**, and open the folder: the setup file is inside.

Build files are kept for 30 days; if none is listed, ask for a new build.
