# Diagnosis at head: the production-readiness review re-verified

**As of:** 2026-10-31. **Head:** `e723fd5` on `docs/handover-pack`; its code is identical to `b5bf413` (the only
commit after it adds the four plan files, 909 lines of Markdown), so every finding below was measured on the code the
review read. **By:** Claude Code, for Jay. **Read with:** `docs/reviews/2026-11-01-production-readiness-review.md`
(the claims), `docs/plans/2026-11-handover-plan.md` (the plan of record), `docs/adr/0024-handover-plan-decisions.md`.

**How it was checked.** Every count was re-measured with a command (listed in the appendix), every file and line was
opened. The disk figures were measured, not estimated: 8 synthetic boards drawn by `tools/make_synthetic_dataset.py`,
scaled to 5 MP (2592 × 1944) the way `tools/perf_compare.py` scales them, inspected and saved through
`AppContext.log_result` on a workspace trained with the shipped settings (AI input 256 px). The four AOI Standards were
read in full from their Claude Docs links. Nothing here is an accuracy claim: no real board has been inspected.

**Words used.** *Holds*: the claim is right at head. *Moved*: right in substance, the number or line differs.
*Wrong*: the claim does not hold. *Missed*: a finding the review does not make.

---

## 1. Layer verdicts

| Layer | Verdict | One line |
|---|---|---|
| Frontend (`aoi/ui`) | **REFACTOR IN PLACE** | Sound widgets, theme and role rules; too much logic and untyped dictionary reading in pages; the inspection cycle lives in a page |
| Backend engine (`aoi/core` minus `services.py`) | **KEEP** | Qt-free, tested, verdict maths pinned by the regression set; add `cycle.py`, fix two small inversions |
| Service layer and API (`services.py`, the UI-engine contract) | **REFACTOR IN PLACE** | Correct rules (roles, transactions, audit, acting user) inside one 3,787-line class with no typed contract |
| Database and data layer (`aoi/data`, migrations, files on disk) | **KEEP the core, REFACTOR IN PLACE the policy** | The SQLite and file-writing core is the best part of the code; what is kept on disk, for how long, and where, is not governed |
| Monitoring and operations | **REFACTOR IN PLACE, mostly new build** | What exists (JSON-lines log, audit, alarms) is sound; heartbeat, disk guard, crash record, support bundle, metrics do not exist. Nothing to rebuild, so not OVERHAUL |
| Deployment | **REFACTOR IN PLACE** | Supply chain is strong; version identity, rollback, autostart and signing custody are not |
| Tests and CI | **REFACTOR IN PLACE (restructure)** | Behavioural, deterministic, traceable; too slow (CI now 45 to 68 min per OS), timing asserted on shared machines |
| Documentation and process | **REFACTOR IN PLACE** | Content traceable and largely right; form unreadable by a successor; rules of record outside the repository |

No layer earns OVERHAUL. The details follow.

### 1.1 Frontend (`aoi/ui`): REFACTOR IN PLACE

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| Lines | 16,247 (`pages/` 12,503) | 16,247 (12,503) | Holds |
| String-key subscripts `["key"]` in `aoi/ui` | 726 raw (`training_versions.py` 104, `training.py` 101, `model_test.py` 101, `logs.py` 79) | 655 on service results (101, 97, 89, 75) | Moved: my count is raw (includes subscripts of local dicts); the review's is a narrower filter it does not state. Same four files lead; the order of magnitude holds |
| UI files importing `aoi.core.services` | 23 | 24 | Moved by one |
| UI files importing engine modules other than the service | 31 (50 import lines) | 32 files, 54 symbols | Holds within counting method |
| Hand-rolled `Worker(` constructions in pages | 11, in 8 page files (plus 25 calls of `Page.run_in_background`) | 11 | Holds |
| The inspection cycle in a page | `aoi/ui/pages/inspection.py:296-386` (`next_board`: engine check, build, load, inspect, `log_result`, moved-run detection, alarms) | same lines | Holds |
| `QTranslator` installed | none in `aoi/` or `main.py`; Language setting has no effect | none | Holds |
| Korean strings finished | 504 of 1,911 (1,407 `unfinished`) = 26 % | 504 of 1,911 | Holds |
| mypy strict on `aoi/ui` | green, 29 s for the whole configured set | green | Holds |

**Named items:** cycle out of the page (E.1), typed results re-pointed page by page (3.3a to d), workers absorbed into
`Page.run_named` (3.4), pages forbidden from executing engine functions (3.5), translator installed (F.1). **Keep:** the
theme token system, the size and contrast walk, `ImageView`, the role gating, the screenshot determinism.

### 1.2 Backend engine (`aoi/core` minus `services.py`): KEEP

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| `aoi/core` lines | 9,418 (of which `services.py` 4,391) | 9,418 | Holds |
| No Qt in `core` and `data` | `tests/test_layers.py:46-69` scans source and imports in a subprocess | same | Holds |
| `Inspector.judge` hard-coded | `aoi/core/inspector.py:358-480` | `322-480` | Moved: 322 is `inspect`; `judge` starts at 358 |
| `aoi/hal` imports `core.imaging` | `aoi/hal/__init__.py:21` | same | Holds |
| `FolderCamera` used by production code | no (only in `aoi/hal`) | no | Holds |
| `Camera.grab()` returns a bare array | yes (`aoi/hal/__init__.py:26-77`) | yes | Holds |
| Job runner | `aoi/core/jobs.py:184-216`, context propagation at 199 | same | Holds |

The engine's maths and its defences stay as they are; the regression set pins them. **Named items, small:** `cycle.py`
(new, moved from the UI), `VIEWS` out of `aoi/hal`, a frame source that returns `(frame, metadata)`. Promote `judge` to
stages only when a Stage 2 check is scheduled. **Not measured here:** p95 verdict time on the reference PC (does not
exist yet). On this cloud machine (4 vCPU Xeon 2.10 GHz) the engine alone, AI off, took a 5 MP median of 544 to 645 ms
and a p95 of 847 to 1,690 ms across three runs; the 1 s p95 budget (REQ-INSP-007) is therefore unproven at 5 MP even
before the AI check runs. See 1.7 for why the timing test failed here.

### 1.3 Service layer and API: REFACTOR IN PLACE

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| `AppContext` span | `aoi/core/services.py:505-4291`, 3,787 lines | same | Holds |
| Methods | 203, of which 144 public | 203 / 144 | Holds |
| Public methods returning `dict[str, Any]` (alone, in a list or optional) | 63 | 63 | Holds |
| `TypedDict` in `aoi/` | 0 | 0 | Holds |
| `Any` in `aoi/` | 520 occurrences (467 lines) | 520 | Holds |
| `ANN401` off | `pyproject.toml:14` (`ignore = ["ANN401"]`), reason at 11-13 | `pyproject.toml:12-14` | Holds |
| Test files reaching `ctx.db` | 77 | 78 | Moved by one |
| `except Exception` handlers in `aoi/` | 32 | 32 | Holds |
| `@requires` and the acting-user variable | `services.py:369-445`, `jobs.py:199` | same | Holds |
| `log_result` compensates file writes | `services.py:1676-1735` (`_remove(files)` on failure) | `1693-1735` | Holds (the method starts at 1676) |
| `previous_model` audit scan | `services.py:3839` | `3848` | Moved by 9 lines |

The rules the class enforces (role on every write, one transaction per write with its audit entry, a job acting as the
person who started it) are correct and must survive the split. The defect is shape, not substance: no contract a page,
a test, a camera loop or a second process could hold to.

### 1.4 Database and data layer: KEEP the core, REFACTOR IN PLACE the policy

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| WAL, `synchronous=FULL`, foreign keys | `aoi/data/db.py:75-82` | same | Holds |
| Migrations | 27 (`0027_dataset_assurance.sql` last); `v0.3.0-rc.1` has 22 | 27 / 22 | Holds |
| Nested `transaction()` joins without `SAVEPOINT` | `db.py:106-129` | same | Holds |
| `archive_old` only sets a flag | `db.py:848-859` | same | Holds |
| Retention runs only at start-up | `services.py:539-541` (`archive_old`, then `_sweep_ok_maps`) | same | Holds |
| What the start-up sweep deletes | OK results' two map files older than 7 days (`map_retention_days_ok`, `aoi/config.py:80`); WARN and NG maps, every overlay, every log file and every migration backup are kept forever | "log files, migration backups, test-run overlays and orphans never deleted" | Holds, and **missed**: WARN boards keep their maps forever too |
| Workspace on a network share or OneDrive accepted | yes: the only OneDrive check guards a recovery key's copy (`services.py:448-452`, used at 3414) | yes | Holds |
| Seeded users without passwords | `db.py:90-92` | yes | Holds |
| Users table keyed by name in inspections | `inspections.operator` holds a name | yes | Holds |

**Disk, measured.** Bytes written per 5 MP board by `log_result` (8 boards; PNG settings as shipped):

| File | Mean | Range | Kept |
|---|---|---|---|
| Overlay (lossless PNG, full resolution) | 4.67 MB | 4.62 to 4.85 MB | forever, every verdict |
| Difference map (`_diff.png`) | 1.49 MB | 1.44 to 1.54 MB | OK: until the first start-up 7 days later; WARN and NG: forever |
| AI map (`_ai2.png`, 16-bit) | 1.52 MB | 0.05 to 2.10 MB | as the difference map |
| **Total at save** | **7.68 MB** | 6.13 to 8.49 MB (median 8.02) | |
| Database row (inspections pages only) | about 5.6 KB | result JSON 1.4 to 9.7 KB | forever (archived flag only) |

The review said about 16 MB at save, 8 MB kept for an OK board and 16 MB for an NG board. **Measured on synthetic
boards that is about twice the truth: 7.7 MB at save, 4.7 MB kept per OK board, 7.7 MB per NG board.** Caveat, stated
plainly: these boards are 640 × 480 drawings scaled up, which compress better than a camera's photographs; a real 5 MP
photograph saved as lossless PNG is larger. The ceiling is the raw size: 15.1 MB overlay (24-bit), 5.0 MB difference
map, 10.1 MB AI map (16-bit), 30.2 MB per board. No real photograph is in the repository, so the real figure is
unmeasured; the review's 16 MB is plausible for real photographs, not a measurement.

Arithmetic at one board every 10 s, 24 h a day: 8,640 boards a day, nearly all OK.

| Case (1 TB SSD, about 920 GB free for the workspace) | Grows by | Full on |
|---|---|---|
| Restarted at least daily (the start-up sweep runs) | overlays 40.3 GB/day forever + OK maps 26.0 GB/day held for 7 to 8 days (about 208 GB) | **day 18** |
| Never restarted (the sweep never runs) | 66.3 GB/day | **day 14** |
| One 8-hour shift a day (2,880 boards), restarted daily | 13.4 GB/day + about 69 GB of maps | day 63 |
| 2 TB SSD (the Customers & Launch recommendation), 24 h, restarted daily | as the first row | day 43 |
| Real photographs at the review's 16 MB per board, never restarted | 138 GB/day | day 7 |

So the review's "full in about a week" is the worst case, not the measured one; on synthetic boards it is two to two
and a half weeks. Every row still fills well inside six months, so the conclusion stands. Not counted above: the
original images. Today the operator loads them from wherever they are and the app copies nothing; with the watched
folder of REQ-INSP-020 each original moves to `done/` on the station's disk, another 4.7 MB per board (40.8 GB/day),
which roughly doubles the rate. D1 does not yet say what happens to them (see ADR 0024).

**What happens on the full disk (re-traced).** `save_image` raises `ENOSPC` inside `log_result`; the files it wrote are
removed and the error reaches the page as a dialog, so the run stops behind it. The alarm insert and the log line that
would record it need the same disk, and the log handler's fallback is `stderr` (`aoi/logging_setup.py:61-62`), which a
windowed build does not have: nothing durable records why. At the next start the review says the retention `UPDATE`
hits `SQLITE_FULL` and the app refuses its own workspace with AOI-SET-011. **That holds only from day 31**, when
`archive_old` (`services.py:539`) first has rows older than `log_retention_days` (30) to flip; before then it writes
nothing, the following `_sweep_ok_maps` frees the OK maps older than 7 days, and the station opens and fills again
within a day or two. From day 31 a full disk makes the station refuse to open until someone deletes files by hand.

### 1.5 Monitoring and operations: REFACTOR IN PLACE, mostly new build

| Capability | At head | Review said | Status |
|---|---|---|---|
| Structured log | JSON lines, one file per UTC day (`aoi/logging_setup.py:38-39`), `app_version` on every line | "no rotation" | **Wrong in part:** files are rotated daily, as the Engineering standard asks; what is missing is deletion and compression. Never deleted: about 1 KB per board, under 2 GB in six months, not a disk risk |
| Free-space check | none in `aoi/` or `tools/` (no `disk_usage`, `statvfs` or `GetDiskFreeSpace`) | none | Holds |
| Heartbeat, health file, counters, `app.close` | none | none | Holds |
| Crash record | no `faulthandler` anywhere | none | Holds |
| Start-up self-check | `aoi/selftest.py` is the build's smoke test, not a station check | same | Holds |
| Support bundle, About | none (REQ-LOG-007, REQ-SET-011 were MUST 1.0, unbuilt) | none | Holds |
| Alarms | table with code, time and message; last 1,000 survive a restart (REQ-INSP-006) | exists | Holds |
| Audit trail | append-only by trigger; shown on no screen and in no export | same | Holds |

### 1.6 Deployment: REFACTOR IN PLACE

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| `APP_VERSION` | `0.3.0` (`aoi/config.py:20`) at `v0.3.0-rc.1` (`31af2f7`, 22 migrations) and at head (27); 181 commits between (128 without merges) | same | Holds |
| Build Python | `3.11` only (`.github/workflows/build.yml:40`) | same | Holds |
| PFX and password in the job-level `env` | `build.yml:55-57` | same | Holds |
| Installer says "(internal, unsigned)" | `installer/aoi.iss:39`, file name `…-unsigned` at 55 | same | Holds |
| VERSIONINFO on the exe | none (`installer/aoi.spec:74`, `EXE(...)` has no `version=`) | none | Holds |
| Rollback | six manual steps (`docs/install/install.md:116-124`) | same | Holds |
| Settings | per-user `settings.json`, 13 keys, no schema version (`aoi/config.py:73-88`) | same | Holds |
| Autostart, restart on failure | none in `installer/aoi.iss` | not stated | **Missed:** after a Windows Update reboot the station sits idle until a person starts the app |
| Pilot CA key | `-KeyExportPolicy NonExportable` in `CurrentUser\My` (`tools/new_pilot_signing.ps1:41-44`); leaf valid 13 months (line 53) | same | Holds |
| Install, self-test, uninstall on every build | `tools/check_installer.py`, `tools/smoke_test_build.py` | same | Holds (keep) |

### 1.7 Tests and CI: REFACTOR IN PLACE (restructure)

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| Test functions | 1,009 `def test_` | 1,009 | Holds |
| Test files | 157 `test_*.py` (167 `.py` under `tests/`) | 157 | Holds |
| Test lines | 40,425 in `test_*.py`, 41,612 in all of `tests/` | 39,728 | Moved: neither of my counts gives 39,728; immaterial |
| Collected test cases (with parameters) | 1,525 | — | — |
| **Full local run (this machine)** | ruff check 1 s, ruff format 0 s, mypy 29 s, **pytest 51 min 13 s** (3,073 s): 1,520 passed, 4 skipped, **1 failed** | — | Baseline recorded |
| CI wall time per OS | last `main` run (2026-10-14, run 38552427032): Linux 44 min 49 s, **Windows 68 min 25 s**, ceiling 75 min (`ci.yml:70`); it started 59 min after it was queued behind the previous push | "20 to 42 minutes per OS leg" | **Moved, worse:** the Windows leg is now 7 minutes from its ceiling |
| Serial, no `xdist`, no timeouts or reruns | `ci.yml:96` runs `pytest -q --cov` | same | Holds |
| Every UI test builds `MainWindow` on a `copytree` | `tests/conftest.py:228` (`restored`) | `228-240` | Holds |
| Demo bundle trains 20 epochs | `tools/make_demo_bundle.py:49` | same | Holds |
| Screenshot fixture module-scoped | `tests/screens/conftest.py:14` | same | Holds |
| Approved screenshots | 65 PNGs; 108 commits touch `approved/` (103 without merges); 593 blobs, **190.3 MiB** of history | 65, 108, 190 MiB | Holds |
| Commits | 880 on the branch: 504 authored, 376 merges, 2026-10-01 to 2026-10-14 (plus this one) | 879 in 14 days | Holds; "36 a day" is the authored count |
| `aoi_ko.ts` churn | 284 commits (254 without merges) | 284 | Holds |
| Shared helpers | 264 imports of test modules by tests, 45 distinct modules; `_window` defined in 4 files, imported by 58 | 264, 46, 4, 55 | Holds |
| Coverage gate | 80 % on `aoi/core` and `aoi/data` only (`pyproject.toml:38`, `fail_under = 80` at 45) | same | Holds |
| Timing test | `tests/perf/test_timing.py` **failed here**: 5 MP median 544 ms against a baseline of 454.8 ms recorded 2026-10-02 for this same cloud fingerprint ("Linux-x86_64-4cpu-Intel(R) Xeon(R) Processor @ 2.10GHz"); two reruns alone: 645 and 632 ms | "skips everywhere but one machine" | **Moved:** it compares only where `tests/perf/baseline.json` holds the machine's fingerprint (one entry, this cloud machine's); elsewhere it asserts the 0.3 MP budget and passes uncompared, it does not skip (`tests/perf/test_timing.py:100-110`). This diagnosis ran on that one machine. The engine is unchanged since the baseline, so this is the noise the review warned about, or this environment (see the caveat below). Either way it is a red test on an unchanged build |

**Environment caveat.** `download.pytorch.org` is blocked by this session's network policy, so the locked
`torch==2.14.1+cpu` could not be installed; `torch==2.14.1` from PyPI (the CUDA build, run on CPU) was used, without
hash checking. Every other package came from `requirements-dev.lock` with hashes. The timing test does not use the AI
model, but the different PyTorch build may change thread settings OpenCV shares; the failure is recorded, not
explained. CI's own Linux leg passed the same test on 2026-10-14.

**Trace gate at head**, on this run's results: `python tools/trace_matrix.py --junit test-results.xml --git-log --gate
G1` reports one problem, `REQ-INSP-007 (MUST G1): FAIL (1 of 6 failing)`, the timing failure above; the same command
on the register before this PR reports the same single problem. The eleven rows this PR adds and the ten it moves add
none (section 4 of the PR note).

### 1.8 Documentation and process: REFACTOR IN PLACE

| Measure at head | Value | Review said | Status |
|---|---|---|---|
| `docs/ARCHITECTURE.md` | 1,477 lines, titled "Architecture & Navigation (v0.1 draft)" | same | Holds |
| ADRs | 23 in `docs/adr/` (0024 drafted by this PR) | 23 | Holds |
| Standards | four Claude Docs pages linked from `CLAUDE.md:11-14`; all four readable today, none in the repository | "chat-tool artifacts outside the repository" | Holds in substance: readable, but not versioned with the code |
| Brief of 2026-10-11 committed | no (`docs/plans/2026-10-business-readiness-progress.md` says so) | no | Holds |
| Support instruction | "send that log file to support" (`docs/manual/engineer.md:47`) | same | Holds |

**Missed by the review and the plans (process):**

1. **Two meanings of G1.** The Charter's G1 is "a customer signs a validation report"; the register's 71 "MUST G1" rows
   were written for it, and `ci.yml` gates on it. The handover plan calls that gate G2 and uses G1 for "safe to run".
   Today nothing breaks (every MUST G1 row passes except the timing flake), but the first time a sentence says "G1"
   it will mean two things. ADR 0024 asks Jay to choose.
2. **MUST conflicts in the Standards that the plans do not record.** Engineering, "Disk and retention (MUST)": "nothing
   is deleted without an Admin action", and "Logs archive after 30 days". REQ-LOG-010's timer sweep, D1's 7-day OK
   maps and the plan's "90 days, gzip after 7" conflict with both, and so does the start-up OK-map sweep already
   shipped. Engineering, "Signing (MUST)": release builds "after two people approve" and the code-signing key "in a
   hardware token or cloud signing service"; Jay works alone and the pilot CA key is a non-exportable software key.
   Each needs Jay's explicit approval as a numbered decision (CLAUDE.md rule 2); ADR 0024 drafts them as D20 to D22.
3. **Inconsistencies inside the plan of record.** G3's tag is `v0.4.1`, which Stage 2 already takes; REQ-TST-009 and
   -010 are "MUST G1" in section 5 but built in G4 and G5 (Prompt 16); D1, D3 and D7 differ between the production plan
   and the handover plan (the handover plan wins, as Jay said; ADR 0024 uses its wording).
4. **Customers & Launch, "Customer profiles (MUST)"**: language, retention, default thresholds and report logo in a
   versioned profile per customer. The plan builds it as REQ-SET-014 in Stage 3, after G1, yet D1's retention is a
   per-factory setting needed at G1. PR 1.2 has to put the policy somewhere; say where.

---

## 2. Six months unchanged in a factory: what breaks, when, how badly

The build at head, installed on a 1 TB station, run by operators who load folders and press Start, one board every
10 s around the clock, no one from our side touching it. Day 0 is installation.

| # | Failure mode | When | How badly | Evidence |
|---|---|---|---|---|
| 1 | **Verdicts on the factory's boards are unmeasured** | Day 0, and every day after | Highest. No real board has ever been inspected; a missed defect is found only by the factory's customer. Nothing here can say how often | No photograph of a real board in the repository; REQ-INSP-014 "No: not measured on real boards"; G2 not run |
| 2 | **Anyone can act as Admin** | Day 0 | High for a quality instrument: the audit trail names whoever was picked, not who acted; an Admin can delete inspection records (with a reason, audited under the picked name) | `services.py:581-590` ("records who was picked, not who proved it"); `db.py:90-92` seeds three users with no password; 17 `@requires("Admin")` methods |
| 3 | **Install blocked or warned by the site's application control** | Day 0 | Medium: install needs IT to trust an unsigned or pilot-signed build; the installer calls itself "internal, unsigned" | `installer/aoi.iss:39,55`; Engineering "Customer sites (MUST)": works under AppLocker or App Control |
| 4 | **Operators read English only** | Day 0 | Medium: the Language setting does nothing; 26 % of strings have Korean; misreading a screen the operator is asked to trust | no `QTranslator`; `aoi_ko.ts` 504 of 1,911 finished |
| 5 | **Workspace on a synced folder** | Day 0 if the workspace is put under Desktop or Documents on a PC with OneDrive folder backup; failures then come at random | High: OneDrive holds and uploads `aoi.sqlite`, `-wal` and `-shm`; AOI-SET-012 "in use" refusals, conflict copies, a damaged database possible; every board image uploaded off site against Customers & Launch "Their data (MUST)" | Accepted: no check (`db.py:76-78` only tests that WAL enables); the only OneDrive guard covers a recovery key (`services.py:3414`). Jay's own approved folders are under `OneDrive\Desktop`: it happens |
| 6 | **Station idle after a Windows Update reboot** | First Patch Tuesday after install (2026-11-10 for an install today), then monthly | Medium: no autostart and no restart on failure; nothing alarms; inspection stops until someone notices | no `[Run]` or Run key in `installer/aoi.iss`; production plan F.3 |
| 7 | **Native crash in PyTorch or OpenCV** | Unpredictable; one access violation seen on Windows CI on 2026-10-09 (fixed by pinning garbage collection to the UI thread) | Medium to high: the screen and the engine share one process, so the operator's screen goes; no crash record, no restart, no clean-exit marker to say it happened | `docs/ARCHITECTURE.md:217-219`; no `faulthandler`; the 8-hour soak has never run on a station (release gate 0.3.0, box 3) |
| 8 | **Disk full** | **Day 14** (never restarted) to **day 18** (restarted daily) on synthetic-board sizes; about day 7 at real-photo sizes if the review's 16 MB holds; day 43 on 2 TB; day 63 at one shift a day | High: the run stops behind an error dialog; the board being saved loses its evidence; no alarm at 80 % because there is no check; until day 30 a restart frees the 7-day-old OK maps and limps on | Section 1.4 measurements; no free-space check in `aoi/` |
| 9 | **Silent I/O failure** | With row 8, and whenever antivirus or a full disk refuses a write | High for support: the alarm row and the log line fail with the save; the windowed build has no `stderr`; afterwards nothing says why the line stopped | `logging_setup.py:61-62` (`handleError`); `log_result` removes its files on failure (`services.py:1733-1735`) |
| 10 | **Station refuses to open its own workspace** | First start after a full disk from **day 31** on (once `archive_old` has rows to flip) | High: the line is down until someone deletes files by hand; AOI-SET-011 with "disk full" | `services.py:539`, `db.py:848-859`, `db.refusal` |
| 11 | **Dataset store key lost** | When IT resets the station account's password as an administrator (not a password change by the user), re-images the PC or moves the station to another account; with a 60- or 90-day reset policy, inside six months | Medium if the recovery sheet was printed and kept: inspection continues, retraining and validation are blocked until it is typed in (AOI-TRN-025). High if the sheet is lost: the customer's training images cannot be opened again | DPAPI key in Windows Credential Manager; ADR 0010; review 5.3 |
| 12 | **Two builds both say 0.3.0** | The first hotfix or second station on another build; the first support call | Medium: an older build refuses the newer database with AOI-SET-002 (safe, not corrupting), but neither the screen nor the log can tell support which build or schema a station runs | `aoi/config.py:20`; 22 vs 27 migrations under one version |
| 13 | **Database grows without bound** | Continuous: about 5.6 KB per board, roughly 50 MB a day, about 9 GB at six months | Low within six months; bites at the first upgrade: the migration copies the whole database synchronously before any window opens (minutes for 9 GB) and needs that much free disk, which row 8 has taken | `db.py:83` (`migrate` backup); measured page usage of `inspections` |
| 14 | **Logs and migration backups never deleted** | Continuous | Low: under 2 GB of logs in six months; one backup per migration | `logging_setup.py:38-39`; no sweep |
| 15 | **Shift check blocks inspection every 12 h** | Every shift, by design | Not a defect: inspection stops at AOI-INSP-016 until the master samples are judged right (REQ-INSP-017). Listed because an unattended station will read it as a stop | `aoi/config.py` `shift_check_hours`; ADR 0014 |

**Summary.** Rows 1, 2 and 5 are present from the first day; rows 6 and 8 to 10 arrive in the first three to five
weeks at 24-hour duty; nothing in the build would tell the company any of it was happening (rows 7 and 9). None of it
is architectural: every row has a named G1 item or a G0 decision.

---

## 3. Restart or refactor

**I confirm "refactor in place, do not restart".** The parts that are hard to get right and slow to rebuild are right
and measured at head: the Qt-free engine with a layer test that fails the build, the crash-safe data core (WAL with full
sync, atomic file writes enforced by a source scan, a checksummed migration runner, audit and label tables made
append-only by 31 triggers), the role and transaction rules in the service, a test suite of 1,525 cases that passed
1,520 here, and a supply chain with hash locks, an SBOM and provenance. Every failure in the six-months table is a
missing policy or a missing small component (a disk check, a sweep, a heartbeat, a crash hook, passwords, a version
bump, an autostart), and every one has a named item in G1. A restart would rebuild the sound core first and reach those
same items later. Where I disagree with the review, it is on degree, not direction: the disk fills in two to two and a
half weeks on measured synthetic boards, not one; the start-up refusal of the workspace needs records older than 30
days, not just a full disk; the logs are rotated daily, they are only never deleted; the timing test does not skip
elsewhere, it passes uncompared, and on the one machine it compares on it failed; and CI is slower than the review says (Windows 68 minutes against a
75-minute ceiling), which makes Stage 2's CI work more urgent, not less. The review and both plans also miss three
MUST conflicts with the Engineering standard (deletion without an Admin action, 30-day log archive, two-person release
approval and key custody) and the two meanings of G1; those need Jay's decisions before G1 code, and none of them
argues for a restart.

---

## Appendix: commands

```bash
git diff --stat b5bf413 HEAD                         # docs only
find aoi -name '*.py' | xargs wc -l                   # 30,013 lines (review 30,056: method differs)
python count_ctx.py                                   # AST walk of AppContext: 3,787 lines, 203/144 methods, 63 dict returns
grep -rohE '\["[A-Za-z_0-9]+"\]' aoi/ui | wc -l       # 726
grep -c 'type="unfinished"' aoi/i18n/aoi_ko.ts        # 1,407 of 1,911
git rev-list --objects --all -- tests/screens/approved | … | git cat-file --batch-check  # 593 blobs, 190.33 MiB
gh run view 38552427032 --json jobs                   # CI leg times
ruff check . ; ruff format --check . ; mypy ; pytest -q --junitxml=test-results.xml
python tools/trace_matrix.py --junit test-results.xml --git-log --out trace-matrix --gate G1
python measure_5mp.py   # make_synthetic_dataset --ok 40 --ng 8, resize to 2592x1944, train 2 epochs at 256 px,
                        # inspect 4 OK and 4 NG through AppContext.log_result, os.path.getsize of the three files
```

The measurement script is not committed (this PR changes nothing under `tools/`); its output, eight lines of
per-board bytes, is in section 1.4. PR 1.2 of G1 is where a committed version belongs.
