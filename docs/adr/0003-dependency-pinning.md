# ADR 0003: Exact pins, hashed lock files, and a license gate in CI

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-01; revised 2026-10-02 for hashed lock files, PySide6-Essentials and the license gate's record
  (#17, S04 follow-up)
- Decides: the product owner (Jay), until a tech lead joins
- Related: #5, stage S04 of the Stage 1 plan; Engineering standard "Code style" and "Scans and SBOM";
  Legal & Compliance standard "Licenses"; Charter checklist line 8

## Context

The Engineering standard asks for "a lock file that pins exact versions", and the Charter's checklist asks that
every dependency has an allowed license and a pinned version. v0.1 declared ranges (`torch>=2.2`) and no lock,
so two installs a week apart could differ, and nothing checked licenses. PyTorch complicates a plain lock: CI and
CPU stations take the CPU build from PyTorch's own index, GPU stations take the CUDA build from another, and
PyPI's Linux wheel pulls in NVIDIA CUDA packages that neither needs in that form.

## Decision

1. `requirements.txt` and `requirements-dev.txt` hold exact `==` pins of the direct dependencies, with the
   license of each in a comment. Qt comes from `PySide6-Essentials`, not the `PySide6` meta-package: the meta-package
   also installs `PySide6-Addons`, whose binaries include Qt Charts, Qt Graphs and Qt Data Visualization, which Qt
   offers under the GPL or a commercial license only, and the Legal standard allows only Qt's LGPL modules
   ("Packaging"). Every Qt module the code imports (QtCore, QtGui, QtWidgets, QtTest) and the translation tools it
   runs (`pyside6-lupdate`, `pyside6-lrelease`) come with Essentials, and a test fails on an import of a module
   Essentials does not ship (`tests/test_check_licenses.py`).
2. `tools/make_lock.py` runs pip-tools (`pip-compile`, BSD-3-Clause) to write four lock files for Python 3.11 on
   Windows and Linux: `requirements.lock` (runtime, transitive, from PyPI), `requirements-dev.lock` (the same
   versions plus the development tools), `requirements-torch-cpu.lock` (PyTorch's CPU build, `2.14.1+cpu`, from
   download.pytorch.org/whl/cpu) and `requirements-torch-cuda.lock` (the CUDA build, `2.14.1+cu130`, from
   download.pytorch.org/whl/cu130, with the NVIDIA libraries it needs on Linux, marked `platform_system ==
   "Linux"`). torch and its NVIDIA packages are kept out of the PyPI locks; torch's other dependencies (filelock,
   sympy, setuptools and so on) stay in `requirements.lock`, so they have one version and one hash set whichever
   build is installed. A Windows-only requirement (`colorama`, which pytest, bandit and build need on Windows) is
   locked with its platform marker, so the output does not depend on the platform that runs the tool.
3. Every lock file records the sha256 of every file of each pinned version, as PyPI and PyTorch's index publish them
   (the tool reads them from the index rather than letting `pip-compile --generate-hashes` download every wheel,
   which for the CUDA build is tens of gigabytes). Every install uses pip's hash mode: the PyTorch lock first with
   `--require-hashes --no-deps`, then `requirements.lock` (stations) or `requirements-dev.lock` (developers and CI)
   with `--require-hashes`, then `pip check`. pip refuses any file whose hash is not in the lock.
4. CI installs that way (the CPU build), runs `pip-audit --no-deps` over the dev lock and over both PyTorch locks
   (by public version, since the vulnerability database does not know `+cpu`), and a "Lock files match their
   inputs" job regenerates the four files with `tools/make_lock.py --check` and fails while any differs.
5. A license gate runs in CI: `pip-licenses --with-system` (MIT) lists the installed packages (without
   `--with-system` it leaves out setuptools, which `requirements.lock` ships) and `tools/check_licenses.py` checks
   the packages named in `requirements.lock` and `requirements-torch-cpu.lock`, the shipped set, against
   `tools/allowed_licenses.txt`. The log is the record: one line per installed package with its verdict (allowed,
   exception pending J8, allowed as named package, NOT ALLOWED), version and the license pip-licenses reports; the
   development and CI tools are listed apart and cannot fail the build; a requirement whose environment marker is
   false on the runner is skipped; and a shipped package that is not installed fails the check, since the gate
   cannot vouch for a package it did not see. The allow-list has two parts: what the Legal standard names (MIT, BSD,
   Apache-2.0; LGPL for Qt as separate libraries, by package name: `PySide6_Essentials` and `shiboken6`; OFL for the
   font), and exceptions the standard does not name that our dependency tree carries: variants of the named
   licenses (MIT-CMU for pillow, 0BSD in numpy, Apache-2.0 WITH LLVM-exception in torch), Zlib and CC0-1.0 parts of
   numpy, Boost parts of torch, PSF-2.0 for typing_extensions and defusedxml, and MPL-2.0 for certifi and
   pathspec. Exceptions count as allowed so CI can pass, but every run prints the ones in use until Jay decides them
   in writing (Stage 1 plan, item J8). A package with no license metadata fails. The GPU build's lock is not
   allowed at all yet: its NVIDIA libraries carry NVIDIA's own licenses and cuda-toolkit declares none, so its check
   fails until J8 decides them package by package (CI installs the CPU build only). No generic line such as
   "Other/Proprietary License" is added for them, since it would pass any proprietary package in the CPU build too.
6. Test tooling is pinned the same way (S05): pytest-qt (MIT) drives the Qt pages offscreen
   (`QT_QPA_PLATFORM=offscreen`) on both CI platforms, and pytest-cov (MIT) reports line coverage of `aoi/core`
   and `aoi/data` on every run. The Engineering standard's 80 % target was reported, not enforced, until the
   Stage 1 suite had grown; at S22 (internal 0.2.0) the suite measured 97.4 % (1,254 statements, 33 missed; the
   lowest module, `aoi/core/imaging.py`, at 87.1 %), so the gate is on: `fail_under = 80` in `pyproject.toml` fails
   a run under it (#114).
7. Development-only packages, pinned in `requirements-dev.txt` and never shipped:
   - defusedxml 0.7.1 (PSF-2.0, an exception pending J8): `tools/trace_matrix.py` parses the JUnit file with it,
     since S07.
   - scikit-image 0.26.0 (BSD-3-Clause): a runtime package in v0.1, moved to development in S08, when OpenCV took
     over the compare step; v0.1's SSIM stays the oracle the tests compare against (`tests/compare_v01_oracle.py`).
   - pillow 12.3.0 (MIT-CMU, an exception pending J8) and tifffile 2026.3.3 (BSD-3-Clause):
     `tests/test_image_input.py` crafts image files with them (a JPEG with EXIF, a BMP, a big-endian TIFF and a
     BigTIFF); they came only through scikit-image until #17 pinned them directly.

## Alternatives considered

- **No hashes, exact pins only** (this record's first draft). Simpler, but pip would install whatever file an index
  serves under a pinned version, and stage S04 asks for hashes; one PyTorch lock per build keeps hash mode workable.
- **`pip-compile --generate-hashes` as is.** It downloads every file it hashes; for the CUDA build that is tens of
  gigabytes per run, more than a CI runner's disk.
- **One lock including the CUDA packages.** CI would download several gigabytes of CUDA libraries it never uses.
- **Checking dev tools' licenses as strictly as runtime.** They are not shipped; they are listed and pinned, and the
  gate reports them, but only the shipped set can fail the build.
- **The `PySide6` meta-package.** One line in `requirements.txt`, but it installs the Addons' GPL-only Qt modules,
  which the app never imports and the Legal standard does not allow in what we ship.

## Consequences

- Upgrades are deliberate: change a pin, run `tools/make_lock.py`, review the diff, open a PR. A pin changed without
  regenerating the locks fails CI (the lock check job, and `tests/test_locks.py` offline).
- `tools/make_lock.py` needs PyPI and download.pytorch.org; where the second is unreachable, `--pypi-only` rewrites
  the two PyPI locks and CI's lock check prints the PyTorch locks as they should be.
- The exception list is a standing item for Jay; when the Legal standard is amended, the entries move from
  `exception:` to plain allowed lines.
- GPU stations install under the NVIDIA CUDA runtime EULA, which the Legal standard does not cover yet; that
  decision is also part of J8 and blocks the GPU build (S56), not the CPU one.
