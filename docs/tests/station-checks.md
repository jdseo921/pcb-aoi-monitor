# Station checks on the reference PC

Four checks of Stage 1 need the reference PC itself: its disk, its power and hours of its time. CI runs a short form
of the first two and none of the others. This page says how to run each one, what to record and when it passes. Jay
runs them, or names who does, and signs the record.

**Synthetic boards only.** The soak and the power-off checks inspect boards that `tools/make_synthetic_dataset.py`
draws. Their verdicts are a load for the app, never an accuracy, and are never quoted as one.

## Before any check

- The reference PC as a station runs it: the app installed from the release under test (README, "Install"), the GPU
  driver if the PC has a GPU, Windows set never to sleep (Settings > System > Power), and nothing else running that a
  station would not run. Leave the screen on; if a policy locks it, write that down.
- A folder for the checks outside every station workspace, for example `D:\station-checks`. Run the commands from the
  repository folder with its virtual environment active (`.venv\Scripts\activate`).
- Write down once: PC model, CPU, GPU, memory, the disk and its write-caching policy (Device Manager > Disk drives >
  the disk > Policies; leave it as the station has it), Windows version, the app's version or commit, and the Python
  and PyTorch versions (`python -c "import sys, torch; print(sys.version, torch.__version__)"`).
- Keep every folder a check writes until the record is signed. A failed check is a bug: keep its folder as it is,
  copy it elsewhere before anything else touches it, and open an issue with the copy's location.

## 1. Eight-hour soak (REQ-INSP-011)

Proves: one board every 3 s for 8 hours (9,600 boards) with no crash, a slowdown of at most 10 % and memory growth of
at most 10 %.

1. Start it, with a new folder for this run:

   ```powershell
   python tools/soak.py --out D:\station-checks\soak-2026-10-12
   ```

   The defaults are the requirement's: `--hours 8 --pace 3 --warm-up 10 --device auto`. The tool first draws the
   synthetic boards, makes a workspace in the run's folder and trains its AI model with the app's own training
   settings (60 epochs at 256 px: minutes on a GPU, longer on a CPU), then opens the app's window, signs the Operator
   in and presses Next Board every 3 s. The boards and their saved results take about 0.55 MB each: keep 10 GB free.
2. Leave the PC alone until the tool prints its summary, about 8 hours after the window opened. Do not use the window.
3. Record the summary lines it prints (boards, late presses, the medians and PASS or FAIL), and keep `soak.csv` (one
   line per board: UTC time, seconds from Next Board to the result shown and saved, the process's memory in MB, the
   verdict and the record), `soak.json` (the same summary) and the workspace's `logs` folder.
4. Look in Windows' Event Viewer (Windows Logs > Application) for an application error of `python.exe` during the run,
   and record any.

Passes when the tool prints PASS and Event Viewer shows no application error of the app. PASS means: the run reached
its 8 hours; every board was inspected and saved; no unhandled error reached the app's error hook; and, over the boards
finished after the 10-minute warm-up, the median seconds per board of the last tenth is at most 1.10 times the first
tenth's, and so is the median memory. The warm-up is left out because the first board loads the AI model and the first
minutes fill the caches; a tenth of an 8-hour run is about 940 boards.

To soak on real boards: `--workspace` (a copy of a trained workspace, never a station's own: the run adds 9,600 records
to it), `--board-model` and `--boards` (a folder of board images) together, in place of the synthetic set-up.

## 2. Twenty forced power-offs (REQ-INSP-008)

Proves: 0 finished inspections lost when the power goes during a run. A finished inspection is a board whose result
the app saved: the soak tool writes its line to `soak.csv`, and flushes it to the disk, only after the record is
committed. The board in hand at the cut is not finished; finding its record after the restart is no loss.

Set up once, a 3-minute run that leaves a workspace and the boards for all twenty (its PASS or FAIL does not
matter here):

```powershell
python tools/soak.py --out D:\station-checks\power\setup --hours 0.05 --pace 1
```

Then for each cut, NN from 01 to 20:

1. Start a run of its own on that workspace:

   ```powershell
   python tools/soak.py --out D:\station-checks\power\cut-NN --hours 1 `
       --workspace D:\station-checks\power\setup\workspace --board-model SOAK `
       --boards D:\station-checks\power\setup\boards\test
   ```

2. Once `soak.csv` has at least 20 lines (about a minute), wait a further time between 0 and 120 s, drawn before the
   check (a die, or a list of 20 numbers made in advance), and cut the power: pull the PC's power cord, or switch off
   its power supply or the wall socket. A laptop's battery comes out too. A shutdown, or a short press of the power
   button, is not a power cut.
3. Wait 10 s, restore the power, start Windows and sign in. Do not open the app.
4. Count:

   ```powershell
   python tools/soak.py --check --out D:\station-checks\power\cut-NN `
       --workspace D:\station-checks\power\setup\workspace
   ```

   It opens the workspace as the app's next start opens it, then prints the boards `soak.csv` names as saved, the
   records in the workspace, every problem it finds and PASS or FAIL. A problem is a board of `soak.csv` missing from
   the workspace or with another verdict, a record without its checks or its result, a defect count that does not
   match, an overlay or map that is missing or does not decode, or a database whose integrity check fails.
5. Record a row: cut, the UTC time of the cut (a few seconds after the last line of `soak.csv`), the wait drawn,
   boards saved, records, problems, PASS or FAIL, and anything Windows said at the restart (a disk check, a warning).

Passes when all twenty counts print PASS: 0 finished inspections lost. One FAIL fails the check.

## 3. One hour offline (REQ-SET-003)

Proves: the app makes no network connection and listens on no port while it is used for an hour, with the network
plugged in, so any call it made would go out and show.

`tools/check_offline.ps1` (stage S52) starts the app, lists the
TCP connections and UDP endpoints of the app's processes every 30 s and prints PASS or FAIL at the end:

```powershell
powershell -ExecutionPolicy Bypass -File tools\check_offline.ps1 -Exe "python main.py" -Minutes 60 `
    -Out D:\station-checks\offline-2026-10-12.csv
```

For a built app, `-Exe` names its `AOI-PoC-Inspector.exe` instead. During the hour, use the app as a station does:
load a folder of boards on Inspection and run it, open Compare on a result, test a folder on AI Model Test, export the
records on Logs & Export, and open every page once. Record the script's last lines and keep the CSV file.

Passes when the script prints PASS: the app ran the whole hour and every sample shows 0 listening ports and 0
connections.

## 4. Start-up and page switches (REQ-SET-020)

Proves: the app is usable within 5 s of starting and opens every page within 300 ms, on a workspace with 50 board
models and 100,000 inspection records.

```powershell
pip install -r requirements-dev.txt
pytest -s tests/test_performance_budgets.py
```

The test writes that workspace with `tools/seed_workspace.py` (about 15 s and 470 MB, removed with pytest's temporary
folders), starts the app three times, opens every page twice as the Admin and asserts both budgets. The window is
drawn off screen, as in every test. Record the times it prints: each start's seconds to usable with its phases, and
each page's milliseconds per opening. Passes when the test passes.

## The record

Write the results to `docs/tests/<date>-station-checks.md`: the machine as listed under "Before any check", one
section per check with what was recorded, and who ran it. Then update the rows of REQ-INSP-011, REQ-INSP-008,
REQ-SET-003 and REQ-SET-020 in `docs/requirements/stage1.md`, citing the record. Jay signs it off.
