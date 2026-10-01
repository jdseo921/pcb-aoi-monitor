# ADR 0003: Exact pins, two lock files, and a license gate in CI

- Status: Proposed. Jay's merge of this record accepts it.
- Date: 2026-10-01
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
2. `tools/make_lock.py` runs pip-tools (`pip-compile`, BSD-3-Clause) to write `requirements.lock` (runtime,
   transitive) and `requirements-dev.lock` (runtime plus development tools, constrained to the runtime lock).
   Both resolve against PyPI for Python 3.11. NVIDIA CUDA packages and triton are left out of the lock on purpose:
   the CPU build does not need them and the CUDA build brings its own. `torch==X` is satisfied by both `X+cpu`
   and `X+cuNNN`, so one pin serves every station type.
3. Hashes are not recorded. pip's hash mode needs a hash set per index, and torch comes from two. The lock pins
   exact versions, which is what the standard requires; the SBOM at release (S59) records what shipped.
4. CI installs torch from the CPU index at the locked version, then `requirements-dev.lock`, and runs
   `pip-audit --no-deps` over the lock.
5. A license gate runs in CI: `pip-licenses` (MIT) lists the installed packages and `tools/check_licenses.py`
   checks the packages named in `requirements.lock`, the shipped set, against `tools/allowed_licenses.txt`.
   The allow-list has two parts: what the Legal standard names (MIT, BSD, Apache-2.0; LGPL for PySide6 as
   separate libraries; OFL for the font), and exceptions the standard does not name that our dependency tree
   carries (Zlib and CC0-1.0 parts of numpy, Boost parts of torch, PSF-2.0 for typing_extensions, MPL-2.0 for
   certifi, Unlicense for filelock). Exceptions count as allowed so CI can pass, but every run prints the ones in
   use until Jay decides them in writing (Stage 1 plan, item J8). A package with no license metadata fails.

## Alternatives considered

- **Hashes for everything.** Reproducibility would be stronger, but every CPU/GPU split would need its own lock
  and hash set, and PyTorch's index does not publish metadata pip-tools can resolve from this build machine.
  Revisit when the installer (S56) fixes one torch build per edition.
- **One lock including the CUDA packages.** CI would download several gigabytes of CUDA libraries it never uses.
- **Checking dev tools' licenses as strictly as runtime.** They are not shipped; they are listed and pinned, and the
  gate reports them, but only the shipped set can fail the build.

## Consequences

- Upgrades are deliberate: change a pin, run `tools/make_lock.py`, review the diff, open a PR.
- The exception list is a standing item for Jay; when the Legal standard is amended, the entries move from
  `exception:` to plain allowed lines.
- GPU stations install under the NVIDIA CUDA runtime EULA, which the Legal standard does not cover yet; that
  decision is also part of J8 and blocks the GPU build (S56), not the CPU one.
