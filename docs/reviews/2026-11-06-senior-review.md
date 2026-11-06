# AOI PoC Inspector: senior review of the whole app

**As of:** 2026-11-06. **Asked by:** Jay, 2026-11-06: "Proceed with a discretion assuming you are a strict senior dev
from a company who is reviewing the whole thing the first time and wants it to work properly." **Repository:**
`jdseo921/pcb-aoi-monitor` at `3efc292` (main after #477). **Done by:** Claude, with six reviewer agents (engine,
training, security, build, data, screens), each finding reproduced on that commit or read in the code, then fixed in
its own pull request by Claude or an implementer agent and read again by a reviewer agent that had not seen it.
**Tracking issue:** #488.

## 1. Verdict

The app works as its documents say on the paths a demo takes, and the holds in section 4 are many and real. The review
found no defect that damages the database, but it found 32 defects (and three found twice): 8 P1, 15 P2 and 9 P3. Six of
the P1 can meet a normal shift: a board ID with a dot (ENG-1), a shift CSV open in Excel (BLD-1), a full drive at
opening (DAT-1), an ROI off the image (ENG-2), a recipe with the AI check off (ENG-3) and a switch to a damaged AI model
file (TRN-5); UI-1 and UI-3 are off its path. Seven P1, five P2 and two P3 are fixed in the pull requests of section 3.
One P1 (UI-1) and five P2 waited for the account pull request #479, which Jay merged during this review and which
changed the same code; they are #487, the next train. **UI-1 is an open P1, so a release cannot ship until it is fixed**
(Engineering, "one open P1 bug stops it"). Two P2 and one P3 need Jay's decision (ADR 0024 D26 to D28), and three P2 and
six P3 are follow-ups. A fourth decision, D29, found reviewing PR 7, asks what "No freezes (MUST)" covers; PR 7 and PR 9
wait for it.

Priority, as the Customers & Launch standard defines it and the Engineering standard applies it: **P1** a line
stopped, a missed defect, lost data, a crash or a frozen window (more than 2 s, whatever the cause); **P2** degraded,
with a workaround; **P3** cosmetic or wording, and here also a latent risk no station has met yet, which the
standard's table does not name.

## 2. Findings

Where the fix lives: **PR** is the pull request in section 3; **after #479** is code the account pull request #479
changed, so its fix is in #487's train now that it has merged; **D26 to D28** (and D29) are in section 6; an issue
number is a follow-up of section 7.

| ID | Pri | What was wrong (on `3efc292`) | Where | Now |
|---|---|---|---|---|
| ENG-1 | P1 | A board ID with a dot (`R1.2`, `10.15.30`) cut the result file's name at the dot, so boards wrote over each other's JSON and CSV | `result_files.py:76-83` | PR 2 |
| ENG-2 | P1 | An enabled ROI off the image, or of no size, was skipped by the judge, and one partly off was judged on what was left, so a board was OK with the place the recipe names never looked at; a scale or Golden board set later could move an ROI off | `inspector.py:445-447` | PR 3 (a Golden board set later: section 7) |
| BLD-1 | P1 | A shift CSV held open by Excel on Windows lost its line for good, and AOI-INSP-019 said the board's own files had failed | `result_files.py:79-82`, `services.py:2147-2172` | PR 2 |
| ENG-3 | P1 | With the AI check off, no ROI was judged, yet the AOI checks tab still counted ROIs as covering their checks, and nothing said so | `inspector.py:442-443`, `checklist.py:34-36` | PR 3 |
| ENG-4 | P2 | The result file schema said defect boxes are in the inspected image's pixels; they are in the Golden board's | `result-file.schema.json:39` | PR 2 |
| TRN-1 | P2 | Activate Selected on the active version wrote an activation to itself, after which Roll Back was off | `services.py:4312`, `:4266` | PR 7 |
| TRN-2 | P2 | A store shredded while a training ran: the run saved a plain AI model and Golden board, registered it and made it live; an Inspection run kept judging with the shredded store's AI model (found reviewing PR 8) | `services.py:3928`, `:1646`, `cycle.py:121` | PR 8 |
| TRN-3 | P2 | A retrain aligns to the board model's current reference, which changes after the first go-live, and the AI model does not record which it used, so the same inputs need not give the same AI model (Lineage MUST) | `services.py:1595-1597` | D27 |
| SEC-1 | P2 | The demo's published Admin password was accepted outside the demo; the next start then reset it, leaving no Admin with a password and the station in its first-run state | `passwords.py:73`, `services.py:880-893` | after #479: #487 |
| SEC-2 | P2 | Anyone at Switch User could lock the only Admin for good with 100 wrong guesses, leaving no Admin and no recovery code | `passwords.py:106-107`, `services.py:960-971` | after #479: #487 |
| DAT-1 | P1 | A workspace closed cleanly on a full drive did not open, and AOI-SET-011 said to restore the backup, which loses every record since it | `db.py:85-87` | PR 5 |
| DAT-2 | P2 | A failed shift check's alarm AOI-INSP-016 never reached the log or `alerts.jsonl` | `services.py:2910` | PR 6 |
| UI-1 | P1 | The idle end during the guide's recovery-key step left the key on screen with the window disabled; only killing the app closed it, and the key is never shown again | `main_window.py:832-860` | after #479: #487 |
| UI-2 | P2 | Shortcut keys (F5 to F11, Training's) never counted as input, so an Engineer working by keyboard was signed out after 15 minutes and later boards were recorded as the Operator's | `main_window.py:458-470` | after #479: #487 |
| UI-3 | P1 | Model Test's Export Report and Validation Report drew their PDF on the window's thread: 2.5 s at 48 rows, 6 s at 50 overlays | `model_test.py:925-940`, `:293-301` | PR 9 |
| SEC-3 | P2 | `set_user` and `audit` are public and unchecked: any caller in the process can act as Admin or forge an entry, against "the service layer checks the role on every write" (MUST); a screen calls `audit` itself | `services.py:656`, `:1916`, `main_window.py:1219` | D28 |
| ENG-5 | P3 | The per-board result file carries no checks (metric, value, threshold), against "Results are data (MUST)" and Charter principle 2 | `result_files.py:31-56` | D26 |
| TRN-4 | P2 | A packaged build's AI models record `build 0.4.0.dev0`, never the build's commit, so Lineage (MUST) is unmet in a packaged build | `lineage.py:61-69` | #481 |
| TRN-5 | P1 | A switch never loaded the version's file, so a damaged one went live and every board was then refused | `services.py:4312-4348` | PR 7 |
| TRN-6 | P2 | `nan`, `inf` or `1e999` in an annotation file stopped an import part-way with an uncoded error (also SEC-5) | `annotation_files.py:142`, `156` | PR 4 |
| SEC-4 | P2 | An Engineer's or Admin's session never idles out while their own Inspection run is going | `main_window.py:838-840` | after #479: #487 |
| DAT-3 | P3 | A refused start deleted the marker of a run that had crashed, so its unclean exit was never logged | `services.py:553-561` | PR 6 |
| DAT-4 | P3 | No CI check pins the checksums of shipped migrations; a whitespace edit would refuse every rc.1 workspace | `migrate.py:58-60` | #482 |
| DAT-5 | P3 | The retention sweep deleted files, then wrote its audit entry outside the deletion; a refused entry left them unaudited | `services.py:4641-4654` | #483 |
| DAT-6 | P3 | The engineer manual and the threat model say backups are never deleted; retention keeps the newest 3 | `engineer.md:19`, `threat-model.md:113` | PR 6 |
| BLD-2 | P3 | The windowed build's `--self-test` and `--support-bundle` print nowhere, so runbook step 13's "exit 0" cannot be read | `selftest.py:38-48`, `runbook.md:48-49` | #484 |
| BLD-3 | P3 | The version-bump check lets everything through after an RC tag, and the RC tag's spelling differs between the runbook and `flags()` | `check_version_bump.py:104-106` | #485 |
| UI-4 | P3 | Export AI Model says nothing on success, and its refusal is logged as unhandled | `training.py:1165-1173` | #486 |
| UI-5 | P2 | Home reads the samples 6 times per opening: 352 to 373 ms at 1,823 samples, against 300 ms | `main_window.py:305` | after #479: #487 |
| TRN-7 | P3 | The import sheet never says why an annotation file gave no box (a file over 1 MB, a document type, a bad number): ADR 0016 point 4 says it does. Found reviewing PR 4 | `sample_import.py:83-85` | #480 |
| UI-6 | P2 | A switch reads the version's Golden board on the window's thread: 119 to 142 ms at 5 MP and 462 to 555 ms at 20 MP, measured with other runs going, against the 100 ms click budget. Found reviewing PR 7 | `services.py:4333` | #489 |
| DAT-7 | P2 | A shred leaves AI Model Test's plain 1600 px overlays of the customer's validation images under `results/test_runs/`, though ADR 0010 point 9 says nothing of the store can be read after it. Found reviewing PR 8 | `services.py:3928-3963`, `:2345` | #490 |

Found twice: SEC-5 is TRN-6, BLD-4 is TRN-4, and the data reviewer found ENG-1 on its own.

## 3. Pull requests

One train, this record first so that every pull request's finding IDs resolve, stacked in this order on #479's head
289a3cb, which main holds since #479 merged, each one concern and under 400 lines
changed by hand, each read by a reviewer agent that had not seen it, `tests/regression/expected.json` unchanged.

| PR | Branch | Findings | Can it change a verdict? |
|---|---|---|---|
| 1 | `docs/senior-review-2026-11-06` | this record, ADR 0024 D26 to D29 | No |
| 2 | `fix/REQ-INSP-021-result-files-keep-every-board` | ENG-1, BLD-1, ENG-4 | No |
| 3 | `fix/REQ-RCP-002-roi-on-the-image` | ENG-2, ENG-3 | Yes: a board with an enabled ROI off the image gets no verdict (AOI-INSP-021), and a recipe or scale that would put one off is refused (AOI-RCP-014, AOI-RCP-015); customer notice in the PR |
| 4 | `fix/REQ-TRN-019-annotation-numbers` | TRN-6 | No |
| 5 | `fix/REQ-LOG-006-full-drive-at-start` | DAT-1: a full drive at opening is AOI-SET-025, which says not to restore a backup | No |
| 6 | `fix/REQ-SET-024-operations-record` | DAT-2, DAT-3, DAT-6 | No |
| 7 | `fix/REQ-TRN-010-model-switches` | TRN-1, TRN-5 | Yes: a version whose AI model file does not load is no longer made active, so the version before it goes on judging; customer notice in the PR |
| 8 | `fix/REQ-TRN-017-shred-during-training` | TRN-2 | Yes: the boards of a board model whose dataset store was shredded are refused (AOI-TRN-058); customer notice in the PR |
| 9 | `fix/REQ-TST-004-reports-off-the-ui-thread` | UI-3 | No |

## 4. What holds

Each was tried, not assumed. Engine: the regression set, alignment, re-grading, Compare. Training: weights-only loads,
the model card required, the rollback walk, Cancel, one run at a time, locked validation sets, one customer per run,
store keys, deduplicated imports, append-only labels. Security: every write role-checked but what anyone at the station,
or the station itself, does and the two D28 names, switching users, lockout across restarts, the recovery code hashed
and single-use, the Argon2id settings, no secret in logs or bundles, the append-only audit, the last-Admin guards, input
limits, Windows Credential Manager. Build: the frozen start, the spec's collection, the hooks, the installer, the
PowerShell scripts, the Windows CI run (1,692 passed). Data: an rc.1 workspace of 3,000 records upgraded to `main` with
nothing lost, a fresh database, retention's selection, the heartbeat, the scrubbed support bundle, the workspace guards
and lock, UTC times. Screens: an empty workspace's start, the guide's whole walk, the five-minute demo script, an
Operator's shift, a switch mid-run, a restart, a button monkey, a deleted record refused.

## 5. Answered, not changed

None. SEC-3 was answered here at first, as a risk only once the API is served to another process. The review of this
record showed that the answer skipped a MUST ("the service layer checks the role on every write") and that a screen
calls `audit` itself, so SEC-3 is now D28 in section 6.

## 6. Decisions for Jay (added to ADR 0024)

Each is a MUST conflict, which CLAUDE.md rule 2 says needs Jay's explicit approval before any code relies on it; if
Jay refuses a proposal, the MUST stays unmet, and that needs his explicit approval too, recorded in ADR 0024.

**D26, the result file's checks (ENG-5).** Engineering, "Results are data (MUST)": `InspectionResult`, `Check` and
`Defect` serialise to JSON unchanged for logs, reports and MES. D10, as Jay confirmed it on 2026-11-03, lists the board
ID, verdict, time, model version, recipe revision and defect list, and no checks. Proposed: each board's JSON result
file also carries its checks as `Check` serialises them, every field unchanged (name, region, source, value,
threshold, rule, verdict, explain); the schema goes to `schema_version` 2, since version 1 allows no other key and a
reader that validates against it refuses the new files, and each customer whose line reads the files is told before it
ships. The one-line CSV and the shift CSV stay as they are.

**D27, what a retrain aligns to (TRN-3).** Engineering, "Lineage (MUST)": retraining the same inputs reproduces the
validation metrics within ±1 percentage point. A training aligns every image to the board model's reference as it is
when the run starts; every switch to a version that stores a Golden board (each Activate, Roll Back and the first
go-live) replaces that reference, and so does Set Reference, and the AI model records neither the reference it used
nor its hash. Proposed: a dataset version records the reference it was frozen with (its file's SHA-256, and a copy kept
encrypted in the customer's dataset store), a run aligns to that one, and the AI model's lineage names it; a version
frozen before this records the reference current at the first run that uses it. REQ-TRN-009's row now says the MUST
is not met, here and through TRN-4.

**D28, role checks on every write (SEC-3).** Engineering, "Offline and least privilege (MUST)": "The service layer
checks the role on every write, because hiding a page is not access control." `AppContext.set_user` and
`AppContext.audit` check no role, and the demo reset's audit entry is written by the screen itself. Every caller today
is the app's own code in its own process. Proposed: `audit` becomes private, and the demo reset's entry is written by
the service that resets the demo workspace; `set_user` stays public, documented as the session's setter that sign-in,
Switch User and the idle end call only after they have checked who it is, until the production plan's PR 4.2 serves the
API to another process and makes it private or role-checked. The other writes `tests/test_roles_and_audit.py` lists as
unchecked stay as they are: each is what anyone at the station, or the station itself, does (signing in, judging and
logging a board, an alarm, an error report, the idle end, the heartbeat, the disk check, the retention sweep, the
close), so a role check would admit every caller, and refusing one would lose its record. `audit` and `set_user` differ:
they let a caller forge an entry or act as another user. Jay's answer covers both kinds.

**D29, work on the window's thread (found reviewing PR 7).** Engineering, "No freezes (MUST)": "Inspection, training,
file and database work never run on the UI thread." REQ-SET-021, `tests/test_no_freeze.py` and ARCHITECTURE hold slow
work to the pool and measure the 2 s line, but on 3efc292 much else runs on the window's thread, and some of it is over
the 100 ms click budget:
- every switch (Activate Selected, Roll Back, What is missing's activate, Inspection's Activate) reads the Golden board,
  119 to 142 ms at 5 MP and 462 to 555 ms at 20 MP (UI-6, #489), and with PR 7 the AI model file, 15 to 22 ms;
- page refreshes read the database: Training's one `boxes` call per NG image, 0.15 to 0.24 s at 1,000 NG images, and
  Home's samples six times, 352 to 373 ms (UI-5);
- writes, among them: Sign In (an Argon2id check, 95 to 115 ms with other runs going, and its audit entry), Save
  Recipe on the Recipe Editor and Compare, Set Scale, Settings' Save, user changes, Unlock User and Confirm Retention,
  Set Reference, Remove on the selected samples (one audited transaction each), the presenter theme's save, and the
  recovery key's and recovery code's sheet saves;
- PR 9 leaves Export Report's read of the AI model card.

These lists come from reading the code, not from a scan. Proposed, for Jay to choose: **(A)** Jay rewords the line in
the standard's source to cover slow work, with a bound a test measures on the window's thread (the click and page
budgets of Engineering's Performance budgets), which then lists every caller over it; those move to the pool as
follow-ups, UI-5, UI-6 and likely Sign In first; PR 7 and PR 9 merge as they are. **(B)** The MUST holds as written:
every caller above moves to the pool in a train of its own, and PR 7's load and PR 9's read move there before they
merge. PR 7 and PR 9 wait for the answer.

## 7. Follow-ups (not in this train)

- **Next, now that #479 has merged,** one train for #487: UI-1 first, as the one open P1, then SEC-1, SEC-2, UI-2, SEC-4
  and UI-5, which change the sign-in, idle and Home code #479 changed.
- **One small pull request each when a train has room:** TRN-4 #481 first (P2, a Lineage MUST gap), UI-6 #489 (P2,
  after D29, needed under either answer) and DAT-7 #490 (P2, Jay chooses which fix), then DAT-4 #482,
  BLD-2 #484, BLD-3 #485, UI-4 #486 and TRN-7 #480; with UI-4, the Training and Inspection buttons that stay on for an
  AI model version that is always refused (found reviewing PR 7).
- **DAT-5 (#483) needs a design first.** Writing the `retention.sweep` entry before the deletions, as first tried, is
  worse: on a full drive the entry is refused before anything goes, so the sweep never frees space, and a file Windows
  holds open gets an entry claiming its deletion every hour. Proposed: keep the deletions first, and carry the counts
  of an entry the database refused into the next sweep's entry.
- **Found while fixing, not introduced by this train:** on a drive too full to write `aoi.running`, a start logs
  `app.not_marked` and writes no marker, and `heartbeat.started` raises before it says the run before was unclean, so
  that run's `app.not_closed_cleanly` is never logged and the clean close then deletes its marker.
- **Found while fixing, left for later:** a workspace on a full drive still does not open, only says so (AOI-SET-025);
  opening it would need SQLite's exclusive locking mode, which no other program could then read. Set Reference, a first
  import and activating an older AI model set a Golden board without checking the recipe's ROIs against it (a camera
  change sets its Golden board before it moves its ROIs, REQ-RCP-006), so the boards after it get AOI-INSP-021, and
  Compare says so on its pane, rather than a refusal there. The rest of the threat model's full-disk row (free
  space, log archiving) describes the gap as it was and needs its own pass with REQ-LOG-006.
- **Left undone by this train's pull requests,** each named in its PR: the result-file alarm AOI-INSP-019's flag is set
  from two threads without a lock (PR 2); a refused training's file that Windows holds open stays under models/ (PR 8);
  a report has no progress or Cancel of its own (PR 9). Two are file work on the window's thread, against "No freezes
  (MUST)", which says file work never runs there, though each is far inside its 2 s: every switch (Activate
  Selected, Roll Back, What is missing's activate, Inspection's Activate) loads the AI model file, 15 to 22 ms (PR 7),
  and Export Report reads the AI model card (PR 9). Both wait for Jay's answer to D29: under (A) they merge as they
  are, and under (B) PR 7's load and PR 9's read move to the pool first.
- **Open issues these pull requests touch but do not close:** #465 (PR 2 keeps a refused shift line, not a board's own
  files while the output folder is unwritable) and #466 (PR 6 keeps the marker of an unclean stop, so it is logged;
  the operator is still not told which board was saved last).
- **Leads not confirmed, Windows only:** Windows ending the session (WM_ENDSESSION) may skip the context's close, so
  every shutdown would log `app.not_closed_cleanly`; the `aoi.running` write has no retry when Windows refuses the
  rename.
- **Residual risk, not defects:** AI inference never runs in the frozen build in CI (its self-test runs with the AI
  check off); `longPathAware` is not verified on a real path over 260 characters; an upgrade while the app runs is
  not tested.
