# AOI PoC Inspector: instructions for Claude Code

**Mandatory.** Every implementation and code change Claude Code makes in this repository follows the
AOI Standards, and other top-tier AI models review Claude's responses and work against them. Work that
would not survive that review is not done.

## Read first

| Standard | Covers | Link |
|---|---|---|
| Charter | Review rules, the checklist for every change, who decides, open decisions, glossary | https://claude.ai/code/artifact/cdb76b42-fd68-42e9-8c59-25abdf86b114 |
| Engineering | Architecture, screens, data, AI models, performance, security, testing, release, workflow | https://claude.ai/code/artifact/346f0966-33e4-4134-9fa6-c0ddad0758db |
| Customers & Launch | Demos, validation and accuracy claims, launch, pricing, support, customer documents | https://claude.ai/code/artifact/af8143f9-f8c3-4f2f-bb40-9646d588c860 |
| Legal & Compliance | Contracts, ownership, privacy, licenses, IP, regulations | https://claude.ai/code/artifact/e99c8a5f-ee90-4fdf-a308-745d4c4edd87 |

If this file and a standard disagree, the standard wins. The technical reference for this build is
`docs/ARCHITECTURE.md`.

## Rules for every change

1. Read the Charter and the standard that covers the work before changing anything.
2. Never skip a MUST. If a request conflicts with one, say so and go ahead only with Jay's explicit
   approval, recorded in the change note. Skipping a SHOULD needs one written line of reason.
3. Show the evidence for every claim of done: the test run and its output, the file and line, or the screen.
4. Write change notes for an outside reviewer: the rules applied, the assumptions made, anything left undone.
5. Fix every review finding, or answer it in writing with the reason it stands.
6. Never approve or merge your own change; Jay signs off.

## Checklist for every change

State the result of each line in the change note; mark a line that does not apply n/a, with a reason.

- [ ] The requirement or bug ID is in the title, and the change traces to a passing test
- [ ] The engine still imports no Qt, and any service API change is typed and documented
- [ ] A schema change ships as a migration, and anything that can change a verdict writes an audit entry
- [ ] Unit, golden-image and screenshot tests pass, and the performance budgets hold
- [ ] Screens are visible only to the roles that need them, meet the size rules, work by touch and
      keyboard, and route every string through `self.tr()`
- [ ] No new network call without a setting, no secret in code, models load as weights only, and the
      scans are clean
- [ ] Datasets and models are versioned, carry a model card and pass the go-live gate
- [ ] Every new dependency has an allowed license and a pinned version
- [ ] Docs, the release note and the demo script are updated wherever the change shows
- [ ] A customer notice is drafted if the change can alter a verdict

## Rules that are easy to break in this code

- `aoi/core` and `aoi/data` never import PySide6; screens reach the engine only through `AppContext`.
- Models load with `torch.load(weights_only=True)` on PyTorch 2.6 or later (`aoi/core/anomaly.py`, since
  REQ-TRN-014); model metadata holds only tensors and plain values, and a test fails the build on
  `weights_only=False` anywhere in `aoi/`.
- Times are stored in UTC as ISO 8601 with an offset, paths relative to the workspace, records with a
  UUID, and every schema change as a numbered migration.
- A control's height comes from the stylesheet: `size_class(widget, "T")` for a 48 px operator target, `"T+"` for a
  56 px run control; `setMinimumHeight()` is undone when the stylesheet is applied, and the size walk in
  `tests/screens/test_sizes_and_contrast.py` fails on the result.
- `aoi/ui` and `aoi/hal` are type-checked (`mypy` strict, every function annotated): write PySide6 enums in full
  (`Qt.AlignmentFlag.AlignCenter`), import `QT_TRANSLATE_NOOP` from `aoi/ui/pages/base.py`, and never give a widget
  attribute a QWidget method's name (`size`, `pos`, `render`); `tests/test_screen_rules.py` fails on one.
- Text is at least 14 pt, colours and sizes come only from `aoi/ui/theme.py`, and every visible string
  goes through `self.tr()` (`QCoreApplication.translate("Page", …)` in the `Page` base class) with named
  `{placeholders}` and `.format()`; after changing a string run `python tools/update_translations.py` and commit
  `aoi/i18n/aoi_ko.ts`, or a test fails. A second test scans `aoi/ui` for a string literal passed to a Qt text setter,
  widget, dialog or table header outside `tr()`; a literal that must stay goes in `ALLOWED_LITERALS` in
  `tests/test_i18n.py` with its reason.
- A change that shows on a screen changes its approved screenshot: run `python tools/render_screens.py --approve` (on
  Linux, with DejaVu Sans installed) and commit `tests/screens/approved/`, or `tests/screens/test_screens.py` fails; the
  diff images it leaves in `tests/screens/actual/` show what moved.
- No GPL, AGPL, non-commercial or unlicensed code, weights or data; only LGPL Qt modules (no Qt Charts).
- Results on synthetic boards are never quoted as accuracy; every accuracy claim carries counts.
- Every error a user can see is an `AoiError` with a code from `aoi/errors.py` (what happened, what to do);
  `docs/error-codes.md` is generated from it with `python -m aoi.errors`, and a test fails when they differ.
- A change that alters a verdict on the synthetic regression set (`tests/regression/`) is re-baselined only
  with an entry in the first section of the release note and Jay's approval of the new `expected.json`.

The full list of v0.1 gaps against these rules is in the Engineering standard, under "Known v0.1 gaps".

## Commands

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python main.py
```

Before pushing, run the checks CI runs on every pull request; all must pass:

```powershell
ruff check .
ruff format --check .
mypy
pytest -q
```
