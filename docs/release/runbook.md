# Release runbook: from the version bump to the kit handed over

The release engineer (today Jay) works down this list for every build that leaves us for a station: a release
candidate, a release, or a pilot build (REQ-SET-027; Engineering standard, "Testing and release" and "Signing"; ADR
0011). Tick each line in the release's pull request or its gate file; a line that does not apply says why. Nothing is
skipped because it passed last time.

## Before the tag

1. [ ] **Bump the version.** `APP_VERSION` in `aoi/config.py` names what ships (`0.4.0`, or `0.4.0-rc.1` for a
       candidate); "Version moves with what ships" passes (`tools/check_version_bump.py`, REQ-SET-023).
2. [ ] **Name the release note.** Rename `docs/release-notes/unreleased.md` to `<version>.md`, start a new empty
       `unreleased.md`, and check the first section, "Changes that can alter verdicts", against every PR since the last
       tag; each verdict change has its customer notice drafted.
3. [ ] **Regression set unchanged, or re-baselined with approval.** `tests/regression/expected.json` changed only with
       an entry in the note's first section and Jay's written approval of the new file.
4. [ ] **Release gate file.** Copy the last `docs/release-gate/<version>.md`, fill each box with its evidence or what is
       open and who closes it.
5. [ ] **Merge** the release PR with all checks green on Ubuntu and Windows; a second person approves (or the written
       exception, J8).

## The build

6. [ ] **Tag** the merge commit `v<version>` and push the tag. `build.yml` refuses a tag that does not name
       `APP_VERSION`.
7. [ ] **CI builds and signs.** On the tag's run of **Windows build**: the .exe and the installer signed with the pilot
       certificate (the log says "Successfully signed" and "Successfully verified", and prints the certificate's expiry;
       a "Renew now" warning means `docs/install/pilot-signing.md`, "Renewal", before the kit leaves), the installer
       installed, self-tested and uninstalled, and the provenance signed.
8. [ ] **Download the kit**: the run's `…-kit` artifact. It holds the installer (`…-pilot-signed.exe`, never
       `…-unsigned.exe`), `SHA256SUMS.txt`, `provenance.sigstore.jsonl`, `trusted_root.jsonl`, `pilot-ca.cer`, the
       release note, `verify.ps1` and `inventory.ps1`.
9. [ ] **Verify the kit on our own PC**: `powershell -ExecutionPolicy Bypass -File .\verify.ps1` in the kit's folder
       prints PASS for every hash, the signature and the provenance, and "All checks passed." CI ran the same script on
       the same kit; this run checks the copy we hand over.

## On the station

10. [ ] **Before the upgrade**: `inventory.ps1` on the station, its output kept with the release record; a support
        bundle (Settings › Support Bundle…); a copy of the workspace with the app closed (install guide, "Backup and
        restore").
11. [ ] **Verify the kit on the station**: `verify.ps1 -SkipProvenance` (a station has no GitHub CLI; step 9 checked
        the provenance), after the customer's IT trusts `pilot-ca.cer` (`docs/install/pilot-signing.md`). IT compares
        the CA thumbprint it prints with the one we send by a second channel, not from the kit.
12. [ ] **Install**, then `verify.ps1 -SkipProvenance -InstalledExe` with the installed .exe
        (`"C:\Program Files\AOI PoC Inspector\AOI-PoC-Inspector.exe"`) and `inventory.ps1`: the new version and
        build number, "(pilot, signed)", signature Valid under the pilot CA.
13. [ ] **Station checks**: `docs/tests/station-checks.md` on this station, its results recorded in the gate file, and
        the app's `--self-test` exit 0. The next hour's `heartbeat.json` shows the new `app_version` and no alarm in
        `logs/alerts.jsonl` but those the station had before.

## Handing over

14. [ ] **Hand over** the kit, the release note (English and Korean), the gate file's open items, and the
        `inventory.ps1` outputs from before and after, to the customer's named contact; record who received it and
        when.
15. [ ] **Close out**: the progress file and the release's issue say the version is on the station; a new
        `unreleased.md` is open for the next one.

If any line fails, the kit does not go: fix it in a pull request, which makes a new build and a new kit, and start again
from the first line that the fix touches.
