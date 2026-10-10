# ADR 0007: A one-folder Windows build from CI, unsigned until the installer and the certificate exist

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-08
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-SET-012 (its build part, and since S57 an internal installer; signing is still open); Engineering
  standard "Build", "Signing", "Scans and SBOM" and "Release 1.0 polish"; Legal & Compliance "Open-source and
  third-party licenses"; Customers & Launch "Demos"; [ADR 0003](0003-dependency-pinning.md); threat model, Spoofing
  row; plan items J6 (code-signing certificate) and J8 (license exceptions, two-person release approval)

## Context

Until now the app ran only from source: Python, a virtual environment and three pip commands on every PC. Jay asked
for a build on GitHub that a reviewer or the reference station can start without Python. The standards fix the
shape of a release: PyInstaller's one-folder mode inside an Inno Setup or MSIX installer, code-signed with a trusted
timestamp, built by CI from a tagged commit after two approvals, with a CycloneDX SBOM, and with every third-party
notice shipped. The installer, the certificate (J6) and a second approver (J8) do not exist yet.

## Decision

1. **PyInstaller, one folder, no console.** `installer/aoi.spec` builds `dist/AOI-PoC-Inspector/` with
   `AOI-PoC-Inspector.exe` and its `_internal/` folder, so the Qt libraries stay separate files a user can replace
   (LGPL). The migrations go in as data. No UPX, which antivirus software often flags. setuptools, pkg_resources,
   distutils and tkinter stay out: only `torch.utils.cpp_extension`, which builds C++ extensions, imports setuptools.
   The QtNetwork module stays out too: only PySide6's own `__init__` imports it, and the app makes no network call
   (Engineering standard, "Offline and least privilege"), so PyInstaller looks for no OpenSSL and none ships. The
   Universal C Runtime is left out, because Windows 10 and 11 include it and always use their own copy.
2. **Pinned and hashed like everything else.** `requirements-build.txt` pins PyInstaller 6.22.3,
   pyinstaller-hooks-contrib 2026.8, and pefile and pywin32-ctypes with their Windows marker; `tools/make_lock.py`
   writes `requirements-build.lock` (the runtime pins plus these) next to the other four locks, CI's lock job checks
   it, `tests/test_locks.py` checks it offline, and pip-audit scans it.
3. **Only checked code ships.** While building, the spec names the installed package every bundled file comes from
   (`tools/third_party_notices.py`) and stops when a file comes from a package outside the shipped set
   (`requirements.lock` and `requirements-torch-cpu.lock`, whose licenses CI's license gate checks) or from anywhere
   other than the app, Python, PyInstaller's work folder and Microsoft's Visual C++ runtime, such as a DLL found on
   the build machine's PATH. PyInstaller looks along PATH for a DLL it finds in no package, so the spec limits PATH to
   Python's folder and Windows' own while it builds; the first CI build had stopped on DLLs from MySQL's, Java's and
   ImageMagick's folders on the runner's PATH.
4. **Notices in the folder.** The spec writes `THIRD_PARTY_NOTICES.txt` beside the .exe: Qt's LGPL notice first,
   with where Qt's source is, then each bundled package's declared license and every license file it installs, then
   Python's license, which covers the libraries Python bundles. The PySide6 and Shiboken6 wheels carry no LGPL text,
   so `installer/licenses/` holds the FSF's LGPL-3.0 and GPL-3.0 texts, copied verbatim from Debian's
   `/usr/share/common-licenses` (SHA-256 `e3a994d8…` and `3972dc97…`, the hashes published for gnu.org's copies).
5. **PyInstaller's own parts.** Its bootloader and loader, embedded in every .exe, are under the GPL-2.0-or-later
   with its Bootloader exception, which allows them in any program without the GPL's terms reaching it; its run-time
   hooks are under Apache-2.0. The Legal standard does not allow GPL code, yet its own "Packaging" rule requires
   PyInstaller. Jay left this J8 line to Claude on 2026-10-08 ("Decide the best one for yourself."), and it is
   allowed by name, for the Windows build only.
6. **CI builds and starts it.** `.github/workflows/build.yml` runs on Windows for every push to main, on demand, and
   on pull requests that change the build. It installs from the hashed locks, builds, starts the .exe on an empty
   workspace with only Windows' folders on PATH, as on a station (`tools/smoke_test_build.py`: "app.start" logged,
   15 s with no error, every migration applied), adds `BUILD-INFO.txt` and `SHA256SUMS.txt`, and keeps the folder as
   the run's artifact for 30 days. After a failed start it rebuilds with a console and starts that, so the log shows
   the error.
7. **An internal test build, never a release.** It is unsigned, has no installer and is named `…-unsigned`;
   `BUILD-INFO.txt` says it must not go to a customer or into a demo. Releases stay as the Engineering standard says.
   The repository is public, so any signed-in GitHub user can download the artifact. Under the same delegation of
   2026-10-08, the build is used for internal tests only until a signed installer exists (J6).

## Alternatives considered

- **Nuitka or Cython**, which the Legal standard suggests (SHOULD) because bytecode decompiles easily. While the
  repository is public the source is public too, so this protects nothing yet; it is worth revisiting with the
  installer, and PyInstaller is what the standards name.
- **PyInstaller's one-file mode.** One .exe is simpler to hand over, but it unpacks to a temporary folder at every
  start and puts the Qt libraries inside the .exe, which the LGPL rule forbids.
- **A GitHub release per build.** It would sit next to the public code as if it were a release; the run's artifact
  is enough for internal tests, and a pre-release waits for Jay to ask for it.
- **The dev lock for the build.** It holds test tools (pillow, scikit-image, pytest) that PyInstaller could bundle
  through optional imports; the build lock holds the runtime and PyInstaller only.

## Consequences

- A reviewer or the reference station can run any main commit without Python: download the run's artifact, unzip it
  and start the .exe. Windows SmartScreen warns about an unknown publisher until the build is signed.
- Each build is about 660 MB unzipped and a 236 MB download, mostly PyTorch (the first green build, of commit
  b0e7435). Actions minutes are free in a public repository; if the repository turns private, each Windows build's
  minutes (counted double) and its artifact count against the plan.
- Still to do for REQ-SET-012: the Inno Setup or MSIX installer with an uninstaller, signing once J6 lands, the GPU
  option with the CUDA runtime (blocked on J8's NVIDIA licenses), the CycloneDX SBOM, the About dialog's notices,
  and a written offer for the Qt source in the EULA and installer.

## Update 2026-10-10 (stage S56): tag builds, a self-test of the build, and the GPU option

Stage S56 of the Stage 1 plan asks for the build half of REQ-SET-012: "CI on a tag builds a one-folder Windows build
that starts, inspects a board, and opens no console window". Decisions 1 to 7 stand; this adds to 6 and 7.

1. **Tags.** `build.yml` also runs on every pushed `v*` tag, beside main, build pull requests and Run workflow. The
   artifact and `BUILD-INFO.txt` carry the tag (`AOI-PoC-Inspector-v0.2.0-g<commit>-windows-x64-unsigned`), and a
   tag that does not name the version in `aoi/config.py` (`v0.2.0`, or `v0.2.0-` and a suffix) fails the build. A
   tag's build is still the unsigned internal test build of decision 7, kept 30 days: signing and the installer come
   with S57 and the certificate (J6).
2. **The build inspects a board.** The .exe has no console and nothing can click in it on CI, so `main.py
   --self-test WORKSPACE [BOARDS]` (`aoi/selftest.py`, no Qt and no window) opens a new or empty workspace folder,
   imports the synthetic regression set's golden board, saves the recipe the set is judged with, inspects one of its
   boards through `AppContext.inspect_file` (the record saved as on the Inspection page), logs `selftest.verdict` with
   the board, its verdict and the one `tests/regression/expected.json` records, and exits 0 when they match, 1 when
   not, 2 on a folder that is not new and empty. The board is `ng_00_missing_component.png`, expected NG. For every
   build the spec runs `tools/make_selftest_data.py`, which draws the set from its seed and keeps `golden.png`, that
   board and `selftest.json` (about 0.5 MB) as the build's `_internal\selftest` folder: drawings only, never a
   photograph or a customer's image, and a pass is never quoted as accuracy.
3. **The smoke test runs the .exe twice** (`tools/smoke_test_build.py`): as before (opens, 15 s with no error, every
   migration applied), then with `--self-test` (exit 0 and the expected verdict logged, with no error). It also reads
   the .exe's PE header: subsystem 2 (GUI), which Windows starts without a console window; the console rebuild that
   CI makes after a failed start is expected to be 3.

The stage, checked against this record: PyInstaller's license is decision 5 (its Bootloader exception lets the
bootloader go into any program without the GPL's terms reaching it, and the Legal standard's "Packaging" rule names
PyInstaller); Qt stays as separate files a user can replace (decision 1); windowed with no console (item 3 checks
it); Python 3.11 and PyTorch's CPU build (`build.yml`, `requirements-torch-cpu.lock`); third-party license texts
(decision 4). **Not done: Noto Sans KR.** The app has no Korean UI yet (REQ-SET-006; when it ships is open in
the Charter) and no font file is in the repository; bundling one adds a third-party file (OFL-1.1, which the Legal
standard allows), so it is left to Jay to say whether it ships now or with the Korean UI, with its OFL text in the
notices.

### The GPU option (documented, not built in CI)

The Engineering standard's "Build" rule asks for a GPU option that bundles the CUDA runtime. On a Windows PC with an
NVIDIA GPU, the same spec builds it from PyTorch's CUDA build; untested so far:

```powershell
python -m pip install --require-hashes --no-deps -r requirements-torch-cuda.lock
python -m pip install --require-hashes -r requirements-build.lock
pyinstaller --noconfirm --clean --distpath dist-gpu --workpath build-gpu installer\aoi.spec
python tools\smoke_test_build.py dist-gpu\AOI-PoC-Inspector\AOI-PoC-Inspector.exe
```

PyTorch's Windows CUDA wheel carries the CUDA libraries it needs inside its own `torch\lib` folder (the lock's
NVIDIA packages are for Linux only), so they ship as part of torch, and the app uses the GPU when Settings' AI device
is auto or CUDA and one is found. CI does not build it: GitHub's Windows runners have no GPU to test it on, and the
NVIDIA licenses of those libraries are not yet allowed (J8, ADR 0003), nor has it been checked that the notices
carry NVIDIA's texts. Until J8 decides them, a GPU folder stays on the PC that built it.

## Update 2026-10-10 (stage S57): an internal installer, unsigned, made with Inno Setup

Stage S57 wraps the one-folder build in an installer for our own tests. Decisions 1 to 7 and the S56 update stand;
decision 7's "no installer" now holds for the folder build only, and the installer is as internal as the folder.

1. **What it installs** (`installer/aoi.iss`). Per machine, into `C:\Program Files\AOI PoC Inspector`: only the
   installer needs admin rights, and the app runs as a standard user (Engineering, "Offline and least privilege").
   x64 Windows from Windows 10 build 19044 (the oldest edition in the Customers & Launch platform table, Windows 10
   IoT Enterprise LTSC 2021); `x64compatible` also lets Windows 11 on Arm run it under emulation, untested. A Start
   menu shortcut, a second one, *AOI PoC Inspector (Demo)*, that starts the .exe with `--demo` (REQ-SET-007), and a
   desktop shortcut that is off unless ticked. The whole build folder goes in, `THIRD_PARTY_NOTICES.txt` beside the
   .exe, and the compile stops when either is missing. The version comes from `aoi/config.py` through ISCC's
   `/DAppVersion` (none is written in the script); the file is `AOI-PoC-Inspector-<version>-setup-x64-unsigned.exe`.
   The AppId is fixed for the life of the product, since Windows finds an earlier install by it; an upgrade deletes
   the old `_internal` folder first, so no file of an earlier build is left to load. No console window: the .exe is
   a GUI program (S56 item 3), and the installer check reads it again once installed.
2. **The uninstaller keeps the workspace.** It removes the program files and the shortcuts only. The script installs
   nothing outside the program folder and has no `[Code]`, `[UninstallDelete]` or `[UninstallRun]`, so the workspace
   (`%USERPROFILE%\AOI_Workspace`, with `settings.json`), the demo workspace beside it and the keys in Credential
   Manager stay; its question before and its message after say so. An upgrade keeps them too, and the app copies the
   database before a migration (`aoi/data/migrate.py`); going back to an earlier build is not one step yet.
3. **Unsigned and internal.** The welcome page, the name in Installed apps (`… (internal, unsigned)`) and the file
   name say so, and `docs/install/install.md` tells Jay how to install it, past SmartScreen. It must never go to a
   customer or into a customer demo: a release is a signed installer from a tagged commit after two approvals.
4. **CI makes and checks it** (`build.yml`). After the folder's smoke test, `choco install innosetup --version 6.7.1
   --allow-downgrade` installs Inno Setup 6.7.1 (Chocolatey's package checks the SHA-256 of jrsoftware.org's
   download; the runner images install the same package and listed 6.7.1 on 2026-10-04), and the job stops unless
   the Inno Setup installed is that version, as its uninstall entry records it (`ISCC.exe` itself carries no file
   version: the first run read 0.0.0). It compiles the script, then `tools/check_installer.py` installs it with
   `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` into a temporary folder, checks the files, the shortcuts and the
   uninstall entry, runs the installed .exe's `--self-test` on a new folder, uninstalls it silently and checks that
   the program files, shortcuts and entry are gone while `AOI_Workspace` and `AOI_Workspace-Demo`, made beforehand
   with a `settings.json`, hold the same files. Only then is the installer kept, as its own artifact
   (`…-windows-x64-unsigned-installer`, 30 days). The job's time limit goes from 60 to 90 minutes.

### Inno Setup's license

- **What ships.** Inno Setup's setup program, inside every installer it makes, and its uninstaller, which the install
  leaves beside the .exe as `unins000.exe`; both unmodified. Nothing of Inno Setup is linked into the app.
- **The terms.** The Inno Setup License (`installer/licenses/InnoSetup.txt`, copied from `license.txt` at tag
  `is-6_7_1` of jrsoftware/issrc, SHA-256 `2e534686…` as published, unchanged at its main branch on 2026-10-10; line
  endings made LF): anyone may use it for any purpose, commercial ones included, and alter and redistribute it,
  provided that (1) source copies keep its notices, (2) binary copies keep every copyright notice and web address in
  place, as in the About box, (3) its origin is not misrepresented (an acknowledgment in the product documentation is
  appreciated, not required), and (4) modified versions are marked. There is no fee, no copyleft and no limit on the
  field of use.
- **Why it is allowed.** It is a permissive license, like the MIT and BSD licenses the Legal standard allows: its
  conditions are the zlib license's plus keeping the notices in binary copies. The Engineering standard names Inno
  Setup for the installer ("Build"). We ship its binaries unmodified, so conditions 2 and 4 hold, and
  `THIRD_PARTY_NOTICES.txt` now carries its notice and license text (`tools/third_party_notices.py`). The Legal
  standard names MIT, BSD and Apache 2.0 by example and Inno Setup's own text is none of them, so, like zlib in
  `tools/allowed_licenses.txt`, it waits for Jay's word with the other license exceptions (J8). The CI license gate
  checks pip packages only, and Inno Setup is not one.
- **A decision for Jay before a release.** jrsoftware.org's order page (read 2026-10-10) *requests* that commercial
  users, for-profit organizations with more than USD 5,000 of yearly revenue, buy a commercial license, also when
  they build installers only for in-house use; it says this "is not strictly required", and that the license may be
  bought later, once the installers are ready to be used in production. The license text asks for no payment, and
  this installer is internal and not in production, so nothing is due now. Before the first installer goes to a
  customer, Jay decides whether to buy one (Single User, Team or Enterprise) or to leave the request, or to use MSIX.

Still to do for REQ-SET-012: code signing of the installer and the .exe with a timestamp (J6); an EULA page with the
LGPL carve-out and the written offer for Qt's source, once counsel has reviewed them; "© year company" in the
installer (Legal, "Notices", SHOULD), waiting for the company and product names; a Korean installer, with the Korean
UI (Inno Setup 6.7.1 ships Korean.isl); a one-step rollback; and the items of the S56 update that remain.
