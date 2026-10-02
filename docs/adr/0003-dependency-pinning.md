# ADR 0003: Exact pins, hashed lock files, and a license gate in CI

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-01; revised 2026-10-02 for hashed lock files (#17, S04 follow-up)
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
   license of each in a comment.
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
5. A license gate runs in CI: `pip-licenses` (MIT) lists the installed packages and `tools/check_licenses.py`
   checks the packages named in `requirements.lock`, the shipped set, against `tools/allowed_licenses.txt`.
   The allow-list has two parts: what the Legal standard names (MIT, BSD, Apache-2.0; LGPL for PySide6 as
   separate libraries; OFL for the font), and exceptions the standard does not name that our dependency tree
   carries (Zlib and CC0-1.0 parts of numpy, Boost parts of torch, PSF-2.0 for typing_extensions, MPL-2.0 for
   certifi, Unlicense for filelock). Exceptions count as allowed so CI can pass, but every run prints the ones in
   use until Jay decides them in writing (Stage 1 plan, item J8). A package with no license metadata fails.
6. Test tooling is pinned the same way (S05): pytest-qt (MIT) drives the Qt pages offscreen
   (`QT_QPA_PLATFORM=offscreen`) on both CI platforms, and pytest-cov (MIT) reports line coverage of `aoi/core`
   and `aoi/data` on every run. The Engineering standard's 80 % target was reported, not enforced, until the
   Stage 1 suite had grown; at S22 (internal 0.2.0) the suite measured 97.4 % (1,254 statements, 33 missed; the
   lowest module, `aoi/core/imaging.py`, at 87.1 %), so the gate is on: `fail_under = 80` in `pyproject.toml` fails
   a run under it (#114).

## Alternatives considered

- **No hashes, exact pins only** (this record's first draft). Simpler, but pip would install whatever file an index
  serves under a pinned version, and stage S04 asks for hashes; one PyTorch lock per build keeps hash mode workable.
- **`pip-compile --generate-hashes` as is.** It downloads every file it hashes; for the CUDA build that is tens of
  gigabytes per run, more than a CI runner's disk.
- **One lock including the CUDA packages.** CI would download several gigabytes of CUDA libraries it never uses.
- **Checking dev tools' licenses as strictly as runtime.** They are not shipped; they are listed and pinned, and the
  gate reports them, but only the shipped set can fail the build.

## Consequences

- Upgrades are deliberate: change a pin, run `tools/make_lock.py`, review the diff, open a PR. A pin changed without
  regenerating the locks fails CI (the lock check job, and `tests/test_locks.py` offline).
- `tools/make_lock.py` needs PyPI and download.pytorch.org; where the second is unreachable, `--pypi-only` rewrites
  the two PyPI locks and CI's lock check prints the PyTorch locks as they should be.
- The exception list is a standing item for Jay; when the Legal standard is amended, the entries move from
  `exception:` to plain allowed lines.
- GPU stations install under the NVIDIA CUDA runtime EULA, which the Legal standard does not cover yet; that
  decision is also part of J8 and blocks the GPU build (S56), not the CPU one.
