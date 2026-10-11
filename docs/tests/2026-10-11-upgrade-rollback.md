# Upgrade and rollback rehearsal, 2026-10-11

A workspace made by an earlier build is opened by the current build, which migrates its database, and then taken
back to the earlier build by the manual route in [install.md](../install/install.md), "Going back to an earlier
build": the earlier build refuses the migrated database (AOI-SET-002), and the backup the upgrade wrote is put back as
`aoi.sqlite`. This record checks that the upgrade keeps every record readable, that the refusal happens, and that the
restored workspace holds exactly the records from before the upgrade.

**Synthetic boards only, run from source.** The boards come from `tools/make_synthetic_dataset.py`. Verdicts on them
prove a code path works; they are not accuracy and are never quoted as accuracy. Neither build was installed: each ran
from a git worktree through `AppContext`, not from its installer, so uninstalling and installing were not rehearsed.

## Set-up

- OLD build: `1516cef` (origin/main, `d4a754a^`, 2026-10-10), the last commit before migration 0020. Its migrations are
  0001 to 0019.
- NEW build: `ce01f92` (origin/main after `git fetch origin main`, 2026-10-11). It adds 0020_test_run_dataset,
  0021_test_run_judged_by and 0022_history_indexes; migrations 0001 to 0019 are unchanged between the two
  (`git diff --stat 1516cef ce01f92 -- aoi/data/migrations` lists only the three new files).
- Each build checked out with `git worktree add --detach <folder> <commit>`, beside the working clone, which was not
  switched.
- Machine: Jay's Windows 11 laptop, CPU only; Python 3.14.2 (the app targets 3.11), PySide6 6.11.2, PyTorch
  2.14.1+cpu, OpenCV 5.0.0, NumPy 2.4.6, in a virtual environment. Nothing installed system-wide.
- Headless: a driver script outside the repository constructs `AppContext(Settings(workspace=<folder>, device="cpu"),
  key_store)` from the build under test (`sys.path` set to that worktree), with `QT_QPA_PLATFORM=offscreen` and
  `AOI_WORKSPACE` set to the rehearsal workspace, so `~/AOI_Workspace` was never opened. The dataset store key went to
  a JSON file in the rehearsal folder through an object with the `Credentials` methods (write, read, delete), not to
  Windows Credential Manager, so it outlived each process. The user was `engineer` throughout.
- Each step ran in a process of its own, closed with `AppContext.close()` before the next.

## Steps and results

### 1. OLD: a fresh workspace

```
python tools/make_synthetic_dataset.py --out <rehearsal>/data --ok 33 --ng 10 --seed 7
```

wrote 22 OK and 3 NG training boards and 11 OK and 7 NG test boards. With OLD, the driver made board model `RH-100`,
imported the 22 OK boards in one call and each NG board with its type (`import_samples`), froze a split version with
`tools/trainable.py` as the tests do, trained with the tests' tiny settings (6 epochs, 64 px; `tests/conftest.py`) in
3.3 s, activated version v1.0 (`activate_model`), and inspected 10 test boards (6 OK, 4 NG) with `inspect_file`, which
saves each record with its overlay, difference map and AI map.

**Pass.** Every record, sample, the active model and the reference image read back (table below). The workspace held
59 files outside the database and logs: 25 imported images, 4 model files (weights `.pt`, Golden board, and the
AI model card as `.json` and `.md`) and 30 result images (3 per inspection). Each file's SHA-256 was recorded.

### 2. NEW: open the same workspace

Constructing `AppContext` with NEW on the workspace migrated it.

**Pass.**

- Backup: `aoi.sqlite.bak-0019-to-0022-20261011T034149Z` was written beside `aoi.sqlite` before migrating, and the log
  holds `schema.backup` (from 19 to 22) followed by `schema.migrated` for 0020, 0021 and 0022. The backup holds schema
  version 19 and the 10 inspections.
- Every old record read: `inspections()` returned the same 10 inspection UUIDs; `inspection_result(id,
  with_maps=True)`, `inspection`, `defects_for` and `checks_for` read all 10 with no error, and each record's overlay
  and map files were there. `samples` returned 25 and each sample image loaded; `models` returned 1; the active model
  v1.0 loaded (`load_model`); the reference image `models/RH-100/RH-100_v1.0_golden.png` loaded.
- The 59 files from step 1 were unchanged (same SHA-256).
- One more board inspected (`ng_009_misalignment.png`, NG), saved as record 11 with its 3 result images.

### 3. OLD on the upgraded workspace

**Pass.** Constructing `AppContext` with OLD raised `MigrationError` AOI-SET-002: "The workspace database was written
by a newer build of the app: it records migration 0020_test_run_dataset, which this build does not have." The
database file was not changed (same size and time).

### 4. Rollback: the backup put back

With no process holding the workspace, `aoi.sqlite` was copied aside, and the backup copied over `aoi.sqlite`:

```
cp ws/aoi.sqlite.bak-0019-to-0022-20261011T034149Z ws/aoi.sqlite
```

The side files `aoi.sqlite-wal` (0 bytes) and `aoi.sqlite-shm` were left as they were.

**Pass.** OLD opened the workspace with no error. It holds schema version 19 and the same 10 inspection UUIDs as
after step 1; the rows of `samples`, `models`, `audit`, `datasets` and `recipes` are identical to a copy of the
workspace taken before the upgrade; every record, sample, the active model and the reference image read back as in
step 1, and `PRAGMA integrity_check` returns ok. Record 11, saved after the upgrade, is gone, as install.md says.

## Counts

| | After step 1 (OLD) | After step 2 (NEW) | Step 3 (OLD, refused) | After step 4 (OLD, restored) |
|---|---|---|---|---|
| Schema version | 19 | 22 | 22, unchanged | 19 |
| Inspections | 10 | 11 | 11 | 10 |
| Defects / checks rows | 22 / 50 | 23 / 55 | 23 / 55 | 22 / 50 |
| Samples | 25 | 25 | 25 | 25 |
| AI models | 1 (v1.0 active) | 1 | 1 | 1 (v1.0 active) |
| Audit entries | 8 | 8 | 8 | 8 |
| Dataset versions / recipes | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| `aoi.sqlite.bak-*` | none | 1 | 1 | 1 |
| Files outside the database | 59 | 62 | 62 | 62 |

## Observations

- After the rollback the 3 result images of record 11
  (`results/2026-10-11/ng_009_misalignment_d31eddc1-…_NG.png`, `…_NG_diff.png`, `…_NG_ai2.png`) stay in the
  workspace with no record pointing to them; OLD's start-up does not remove them. install.md says the records are
  lost but not that their files stay behind.
- install.md's rollback names only `aoi.sqlite`. Here the `-wal` file was empty after a clean close, so leaving it was
  harmless; after a crash it might not be, and the steps do not say to remove `aoi.sqlite-wal` and `aoi.sqlite-shm`
  before putting the backup back.
- The upgrade writes no audit entry (8 before and after); the backup and migrations appear only in the log.
- OLD's AOI-SET-002 text says to update the app or choose another folder; it does not point to the backup. That is
  the earlier build's text and cannot change for builds already shipped.

## Limits

- Synthetic boards, one board model, one view, one model version, 10 + 1 inspections: a small workspace. Migration
  time on a large one (100,000 records, where 0022's indexes matter) was not measured.
- Run from source in worktrees on Python 3.14, not from the installers on 3.11; uninstall and install were not
  rehearsed, nor the folder picker that follows AOI-SET-002 on the GUI.
- The dataset store key was kept in a file for the rehearsal, not in Credential Manager as on a station.
- Only one step back (0022 to 0019) was rehearsed.
