"""AI Model Test Screen (spec 4.3): batch-validate the active model on a labelled folder."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core import stats
from ...core.inspector import InspectionResult, JudgedBy
from ...core.recipe import scale_digits
from ...core.services import AppContext
from ...errors import AoiError, Phrase
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import QT_TRANSLATE_NOOP, Page, breakable, button, cell_item, fill_table, make_table

if TYPE_CHECKING:
    from ..main_window import MainWindow

MATCHES = {  # a row's pass_fail, stored and exported as this English key -> what its column says (#207)
    "PASS": QT_TRANSLATE_NOOP("ModelTestPage", "Matches label"),
    "FAIL": QT_TRANSLATE_NOOP("ModelTestPage", "Differs from label"),
    "NO_LABEL": QT_TRANSLATE_NOOP("ModelTestPage", "No label"),
}
# What judged a run and what is in use now, as AOI-TST-001 and the note name them: phrases, which a screen translates in
# place while the error's own text, which a log would keep, stays English (#250). The preview pane's copy of AOI-TST-001
# also names its files through breakable (#245), so a log would build its own from the plain names
AI_MODEL = QT_TRANSLATE_NOOP("Errors", "AI model {version}")
NO_AI_MODEL = QT_TRANSLATE_NOOP("Errors", "no AI model")
AI_CHECK_OFF = QT_TRANSLATE_NOOP("Errors", "no AI model (the AI check off)")  # a recipe that turns it off (#246)
GOLDEN_BOARD = QT_TRANSLATE_NOOP("Errors", "Golden board {file}")
NO_GOLDEN_BOARD = QT_TRANSLATE_NOOP("Errors", "no Golden board")
SCALE = QT_TRANSLATE_NOOP("Errors", "a scale of {scale:.{digits}f} px/mm")  # the board model's, which sizes in mm use
NO_SCALE = QT_TRANSLATE_NOOP("Errors", "no scale")


class MetricTile(QLabel):
    """A rate as the sketch shows it: its name, its count "n of N" large, and its one-sided 95 % bound under it, never a
    percent alone (REQ-TST-002)."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("tile")
        self.setMinimumHeight(theme.BANNER_H)
        self.set(None)

    def set(self, rate: dict[str, Any] | None) -> None:
        count = "—" if rate is None else phrase_text(stats.COUNT_ONLY.fill(n=rate["n"], of=rate["of"]))
        bound = stats.bound_text(rate) if rate else None
        self.setText(
            f"<div style='font-size:{theme.FONT_PT}pt;color:{theme.TEXT_MUTED}'>{self.name}</div>"
            f"<div style='font-size:{theme.FONT_TILE_PT}pt;font-weight:700'>{count}</div>"
            f"<div style='font-size:{theme.FONT_PT}pt'>{phrase_text(bound) if bound else '&nbsp;'}</div>"
        )


class ModelTestPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "AI Model Test")
    subtitle = QT_TRANSLATE_NOOP("Page", "Labels come from the sub-folder names: ok/ and ng/")
    roles = ("Engineer", "Admin")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.folder: str | None = None  # the folder picked, to run next
        self.rows: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}
        self.run_folder = ""  # the folder the rows and metrics came from, which the report names (#174)
        self.run_board_model: str | None = None  # and the board model they were run for, while shown (#180)
        self.run_judged: JudgedBy | None = None  # and what judged them: AI model, recipe revision, Golden board (#250)

        self.tabs = QTabWidget()  # Run, and History: every stored run, reopened in Run (REQ-TST-005)
        run_tab = QWidget()
        run_layout = QVBoxLayout(run_tab)
        run_layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(button(self.tr("Select Test Folder…"), slot=self.pick))
        self.btn_run = button(self.tr("Run Test"), "primary", self.run)
        bar.addWidget(self.btn_run)
        bar.addWidget(button(self.tr("Export CSV"), slot=self.export_csv))
        bar.addWidget(button(self.tr("Export Report"), slot=self.export_report))
        self.folder_label = QLabel(self.tr("No folder selected"))
        self.folder_label.setObjectName("muted")
        bar.addWidget(self.folder_label, 1)
        run_layout.addLayout(bar)
        src = QHBoxLayout()  # a frozen dataset version's locked validation set, or a labelled folder (REQ-TST-001)
        src.addWidget(QLabel(self.tr("Source")))
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(self._source_changed)
        src.addWidget(self.source, 1)
        run_layout.addLayout(src)

        tiles = QGridLayout()
        self.tiles = {
            k: MetricTile(n)
            for k, n in (  # missed defects and false calls lead (sketch Q45)
                ("missed_defects", self.tr("Missed defects")),
                ("false_calls", self.tr("False calls")),
                ("recall", self.tr("Recall")),
                ("precision", self.tr("Precision")),
                ("accuracy", self.tr("Accuracy")),
            )
        }
        for i, t in enumerate(self.tiles.values()):
            tiles.addWidget(t, 0, i)
        run_layout.addLayout(tiles)
        self.confusion = QLabel("")
        self.confusion.setObjectName("muted")
        run_layout.addWidget(self.confusion)
        self.run_note = QLabel("")  # what judged the run and what is in use now, once they differ (#250)
        self.run_note.setObjectName("muted")
        self.run_note.setWordWrap(True)
        self.run_note.hide()
        run_layout.addWidget(self.run_note)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        run_layout.addWidget(self.bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.headers = [
            self.tr("Image"),
            self.tr("Label"),
            self.tr("Verdict"),
            self.tr("AI score"),
            self.tr("Matches label?", "whether the verdict matches the image's label"),
        ]
        self.table = make_table(self.headers)
        self.table.itemSelectionChanged.connect(self._preview)
        self.empty = EmptyState(self.table)
        split.addWidget(self.table)
        preview = QWidget()
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(0, 0, 0, 0)
        self.preview_verdict = QLabel("—")  # the previewed board's verdict: colour, shape and word (REQ-INSP-002)
        self.preview_verdict.setStyleSheet(theme.verdict_style("INFO", big=False))
        self.view = ImageView(placeholder=self.tr("Select a row to preview"))
        self.busy = BusyOverlay(self.view, self.tr("Inspecting…"))
        self.preview_empty = EmptyState(self.view)  # a row that is not previewed, and why (#250)
        pl.addWidget(self.preview_verdict)
        pl.addWidget(self.view, 1)
        split.addWidget(preview)
        split.setSizes([800, 800])
        run_layout.addWidget(split, 1)
        self.tabs.addTab(run_tab, self.tr("Run"))
        self.tabs.addTab(self._history_tab(), self.tr("History"))
        self.tabs.currentChanged.connect(lambda i: self._fill_history() if i == 1 else None)
        self.root.addWidget(self.tabs, 1)

    def _history_tab(self) -> QWidget:
        """Every stored run of the board model, newest first: its time, AI model, dataset version or folder, what
        judged it, missed defects and false calls; Open shows it on Run (REQ-TST-005)."""
        tab = QWidget()
        hl = QVBoxLayout(tab)
        hl.setContentsMargins(0, 0, 0, 0)
        self.history = make_table(
            [
                self.tr("Time"),
                self.tr("AI model"),
                self.tr("Dataset or folder"),
                self.tr("Settings"),
                self.tr("Missed defects"),
                self.tr("False calls"),
            ]
        )
        self.history.doubleClicked.connect(lambda _i: self.open_run())
        self.history_empty = EmptyState(self.history)
        hl.addWidget(self.history, 1)
        row = QHBoxLayout()
        row.addWidget(button(self.tr("Open"), slot=self.open_run))
        row.addStretch(1)
        hl.addLayout(row)
        self._runs: list[dict[str, Any]] = []
        return tab

    def _fill_history(self) -> None:
        bm = self.board_model
        self._runs = self.ctx.test_runs(bm) if bm else []
        names = {d["uuid"]: d["name"] for d in self.ctx.datasets(bm)} if bm else {}
        rows = []
        for run in self._runs:
            source = names.get(run["dataset_uuid"], run["dataset_uuid"]) if run.get("dataset_uuid") else run["folder"]
            judged = run["judged_by"]
            settings = self.tr("recipe revision {revision}").format(revision=judged.recipe_rev or 0) if judged else "—"
            rates = run["metrics"].get("rates") or stats.validation_rates(run["results"])
            rows.append([
                to_local(run["time"]), run["model_version"] or "—", source, settings,
                phrase_text(stats.text(rates["missed_defects"])), phrase_text(stats.text(rates["false_calls"])),
            ])  # fmt: skip
        fill_table(self.history, rows)
        if self._runs:
            self.history_empty.hide()
        else:
            self.history_empty.show_state(self.tr("No runs stored yet"), self.tr("Run Test stores each run here."))

    def open_run(self) -> None:
        """The run selected on History, shown on Run as it was stored: rows, tiles and previews (REQ-TST-005)."""
        sel = self.history.selectionModel().selectedRows()
        if not sel or (bm := self.board_model) is None:
            return
        run = self.ctx.test_run(self._runs[sel[0].row()]["uuid"])
        if run is None:
            return
        source = str(run["folder"])
        self._show((run["metrics"], run["results"], run["judged_by"]), source, bm)
        self.tabs.setCurrentIndex(0)

    def _fill_sources(self) -> None:
        """The board model's frozen versions whose validation set is locked, newest first and picked, then a labelled
        folder (sketch: the dataset version by default)."""
        self.source.blockSignals(True)
        self.source.clear()
        bm = self.board_model
        for d in self.ctx.datasets(bm) if bm else []:
            split = self.ctx.validation_split(d["uuid"])
            if split is not None and split["validation"]:  # a version split with nothing held out has no validation
                line = self.tr("{name}: its locked validation set, {count} images")
                self.source.addItem(line.format(name=d["name"], count=len(split["validation"])), d["uuid"])
        self.source.addItem(self.tr("Labelled folder (ok/ and ng/ sub-folders)"), None)
        self.source.setCurrentIndex(0)
        self.source.blockSignals(False)
        self._source_changed()

    def _source_changed(self) -> None:
        dataset = self.source.currentData()
        self.folder_label.setText(
            self.source.currentText() if dataset else self.folder or self.tr("No folder selected")
        )

    def pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.tr("Validation folder (with ok/ and ng/ sub-folders)"))
        if d:
            self.folder = d
            self.source.setCurrentIndex(self.source.count() - 1)  # the folder picked is the source now
            self.folder_label.setText(d)

    def run(self) -> None:
        if not self.btn_run.isEnabled():  # a run is going: the preview pane's Run Test Again starts no second one
            return
        if (bm := self.checked_board_model()) is None:
            return
        dataset = self.source.currentData()
        picked = self.source.currentText() if dataset else self.folder  # what the report names as the run's source
        if not dataset and not picked:
            self.pick()
            picked = self.folder
        if not picked:
            return
        folder = picked
        if not self.ctx.active_model(bm):
            QMessageBox.information(
                self,
                self.tr("No AI model"),
                self.tr("No AI model yet: the results use the Golden board comparison only."),
            )
        self.btn_run.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)

        def progress(done: int, total: int) -> None:
            report((done, total))  # the worker's emit, bound below before the job starts

        def on_row(row: dict[str, Any]) -> None:  # each board as it is judged: the table grows (REQ-TST-006)
            report(("row", row))

        if dataset:  # its locked validation set, labelled as frozen
            w = Worker(self.ctx.test_dataset, dataset, progress=progress, on_row=on_row)
        else:
            w = Worker(self.ctx.batch_test, bm, folder, progress=progress, on_row=on_row)
        report = w.signals.progress.emit  # the job holds this emit, never the worker or its signals (#132)
        live: list[dict[str, Any]] = []

        def on_progress(a: tuple[Any, ...]) -> None:
            if a[0] == "row":
                if bm == self.board_model:  # never under another board model's name (#180)
                    live.append(a[1])
                    self._fill_rows(live)
                return
            self.bar.setMaximum(a[1])
            self.bar.setValue(a[0])

        def finished() -> None:
            self.btn_run.setEnabled(True)
            self.btn_run.setText(self.tr("Run Test Again") if self.rows else self.tr("Run Test"))
            self.bar.setVisible(False)
            self._fill_history()  # the run just stored heads the list

        w.signals.progress.connect(on_progress)
        w.signals.result.connect(lambda out: self._show(out, folder, bm))  # folder and board model go with them
        w.signals.error.connect(self.error)
        w.signals.finished.connect(finished)
        start(w, self.ctx.jobs)

    def _show(self, out: tuple[dict[str, Any], list[dict[str, Any]], JudgedBy], folder: str, board_model: str) -> None:
        if board_model != self.board_model:  # the header changed while it ran: its rows are not shown under the
            status = self.tr(  # new board model's name (#180); the run is stored, as every run
                "The AI model test of {board_model} is stored; its results are not shown here, since the board model"
                " changed while it ran."
            )
            self.shell.status(status.format(board_model=board_model))
            return
        self.metrics, self.rows, self.run_judged = out
        self.run_folder, self.run_board_model = folder, board_model
        self.empty.hide()
        self._drop_preview()  # a preview of the run before, still being inspected, never lands beside these (#250)
        self.table.clearSelection()  # nor does a row stay selected beside an empty pane
        self._clear_preview()  # nor a row of the run before, or why it was not previewed
        self._show_note()
        m = self.metrics
        rates = m.get("rates") or stats.validation_rates(self.rows)  # a run stored before rates were (S45)
        for k, t in self.tiles.items():
            t.set(rates[k])
        counts = self.tr(
            "{labelled} labelled of {images} images  ·  TP {tp}  FN {fn}  FP {fp}  TN {tn}  ·  WARN counts as NG"
        )
        self.confusion.setText(
            counts.format(labelled=m["labelled"], images=m["samples"], tp=m["TP"], fn=m["FN"], fp=m["FP"], tn=m["TN"])
        )
        self._fill_rows(self.rows)

    def _fill_rows(self, rows: list[dict[str, Any]]) -> None:
        """The results table: Image, Label, Verdict, AI score and whether the verdict matches the label, a row that
        differs in red (REQ-TST-003); while a run goes, the rows judged so far (REQ-TST-006)."""
        self.empty.hide()
        cells = [[Path(r["image"]).name, r["gt"], theme.verdict_label(r["ai_result"]), r["score"], self._matches(r)]
                 for r in rows]  # fmt: skip
        colors = [theme.NG_COLOR if r["pass_fail"] == "FAIL" else None for r in rows]
        fill_table(self.table, cells, colors, [r["image"] for r in rows])

    def _matches(self, r: dict[str, Any]) -> str:
        """Whether the verdict matches the label, translated; a "?" label from before #207 (PASS) reads No label."""
        key = "NO_LABEL" if r["gt"] == "?" else r["pass_fail"]
        return self.tr(MATCHES[key]) if key in MATCHES else str(key)

    def _preview(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or (bm := self.run_board_model) is None:
            return  # a row is judged under the board model of its run (#180), never the header's after a switch
        path = cell_item(self.table, rows[0].row(), 0).toolTip()
        self._clear_preview()  # the row before never stands beside this one, even when it cannot be inspected (#182)
        row = next((r for r in self.rows if r["image"] == path), None)
        if row is not None and row.get("overlay"):  # the overlay stored as it was judged: shown, never judged again
            self._drop_preview()
            self.run_in_background(
                self.ctx.load_image, row["overlay"],
                on_result=lambda img: self._show_overlay(row, img, bm), busy=self.busy,
                on_error=lambda e: self.not_inspected(self.preview_verdict, Path(path).name, e, big=False),
            )  # fmt: skip
            return
        if (changed := self._judged_now()) is not None:  # never judged by what did not judge its row (#250)
            self._drop_preview()  # nor the row before, still being inspected
            self._refuse_preview(path, changed)
            self._note(changed)
            return
        run = self.run_judged
        self.run_in_background(
            self.ctx.inspect_file, bm, path, save=False,
            on_result=lambda res: self._show_preview(path, res, bm, run), busy=self.busy,
            on_error=lambda e: self.not_inspected(self.preview_verdict, Path(path).name, e, big=False),
        )  # fmt: skip

    def _drop_preview(self) -> None:
        """Cancel a preview still being inspected: run_in_background drops a cancelled job's result and shows no dialog
        for its error, as the Recipe Editor's _drop_try does (#250)."""
        if self._bg is not None:
            self._bg.stop()
            self._bg = None
            self.busy.finish()

    def _clear_preview(self) -> None:
        self.preview_verdict.setText("—")
        self.preview_verdict.setStyleSheet(theme.verdict_style("INFO", big=False))
        self.view.set_image(None)
        self.preview_empty.hide()

    def _judged_now(self) -> dict[str, object] | None:
        """None while the run is current: its board model still uses the AI model, recipe revision, Golden board and
        scale that judged it (`AppContext.engine_is_current`, the comparison Inspection makes, #243, S29), or all but
        what judged none of its images, as a preview gives each row's verdict: the AI model for a run judged with the
        AI check off (#246), the scale for a recipe that holds no size in mm (S29). Otherwise those and the ones in use
        now, by version, revision, file name and px per mm, for the note and AOI-TST-001 (#250); a recipe with the AI
        check off names AI_CHECK_OFF in place of an AI model, the one active then having judged nothing."""
        bm, run = self.run_board_model, self.run_judged
        if bm is None or run is None or self.ctx.engine_is_current(bm, run):
            return None
        recipes, golden, scale = self.ctx.recipe_history(bm), self.ctx.reference_image(bm), self.ctx.scale(bm)
        same_recipe = (recipes[0]["uuid"] if recipes else None) == run.recipe_uuid
        model, recipe = self.ctx.active_model(bm), self.ctx.recipe(bm)[1]
        same_model = not run.use_ai or (str(model["uuid"]) if model else None) == run.model_uuid
        same_scale = scale == run.px_per_mm or not recipe.sized_in_mm  # a recipe in px judges alike at any scale
        if same_recipe and same_model and same_scale and golden == run.reference_path:
            return None  # what changed judged none of the run's images
        ai_now = run.use_ai if same_recipe else recipe.use_ai

        def ai_model(version: str | None) -> Phrase:
            return AI_MODEL.fill(version=version) if version else NO_AI_MODEL

        def golden_board(path: str | None) -> Phrase:
            return GOLDEN_BOARD.fill(file=Path(path).name) if path else NO_GOLDEN_BOARD

        def scale_of(s: float | None) -> Phrase:  # with the digits that tell the two apart (S29 review)
            return NO_SCALE if s is None else SCALE.fill(scale=s, digits=scale_digits(run.px_per_mm, scale))

        return {
            "board_model": bm,
            "run_model": ai_model(run.model_version) if run.use_ai else AI_CHECK_OFF,
            "run_recipe": run.recipe_rev or 0,
            "run_golden": golden_board(run.reference_path),
            "run_scale": scale_of(run.px_per_mm),
            "model": ai_model(model["version"] if model else None) if ai_now else AI_CHECK_OFF,
            "recipe": recipes[0]["revision"] if recipes else 0,
            "golden": golden_board(golden),
            "scale": scale_of(scale),
        }

    def _refuse_preview(self, path: str, changed: dict[str, object]) -> None:
        """A row of a run that is no longer current is not inspected (#250): the banner reads Not inspected, the pane
        shows AOI-TST-001 (what judged the run, what is in use now, what to do), and Use Last Inspected keeps the board
        it had. The callers show the note above the table. The error is the pane's copy, never raised or logged: the
        row's file name and each Golden board's go through breakable, so a long one wraps within the pane (#245);
        `changed`, which the note shows, keeps the names as they are."""
        name = breakable(Path(path).name)
        shown = {
            k: GOLDEN_BOARD.fill(file=breakable(str(v.values["file"])))
            if isinstance(v, Phrase) and v.filled and v.source == GOLDEN_BOARD.source
            else v
            for k, v in changed.items()
        }
        e = AoiError("AOI-TST-001", None, file=name, **shown)
        heading, sentence = self.not_inspected(self.preview_verdict, name, e, big=False)
        what = " ".join([sentence, phrase_text(e.action)])
        self.preview_empty.show_state(heading, what, self.tr("Run Test Again ›"), self._run_again)

    def _run_again(self) -> None:
        """The preview pane's Run Test Again tests the run's folder, as AOI-TST-001 says, even if another was picked."""
        if self.run_folder and self.btn_run.isEnabled():  # while a run is going, run() starts no second one
            self.folder = self.run_folder
            self.folder_label.setText(self.run_folder)
        self.run()

    def _show_note(self) -> None:
        """The line above the table while the AI model, recipe, Golden board or scale of a run is not in use (#250)."""
        self._note(self._judged_now() if self.rows else None)

    def _note(self, changed: dict[str, object] | None) -> None:
        if changed is not None and any(r.get("overlay") for r in self.rows):  # each row shows its stored overlay
            note = self.tr(
                "These results were judged by {run_model}, recipe revision {run_recipe}, {run_golden} and {run_scale};"
                " {board_model} now uses {model}, recipe revision {recipe}, {golden} and {scale}. Each row's preview"
                " shows it as the run judged it; Run Test Again tests the run's source with what is in use now."
            )
            shown = {k: phrase_text(v) if isinstance(v, str) else v for k, v in changed.items()}
            self.run_note.setText(note.format(**shown))
        elif changed is not None:
            note = self.tr(
                "These results were judged by {run_model}, recipe revision {run_recipe}, {run_golden} and {run_scale};"
                " {board_model} now uses {model}, recipe revision {recipe}, {golden} and {scale}. Rows are not"
                " previewed; select one for Run Test Again, which tests the run's folder with what is in use now."
            )
            shown = {k: phrase_text(v) if isinstance(v, str) else v for k, v in changed.items()}  # phrases translated
            self.run_note.setText(note.format(**shown))
        self.run_note.setVisible(changed is not None)

    def _show_overlay(self, row: dict[str, Any], image: Any, board_model: str) -> None:
        """A row's stored overlay with its verdict, as the run judged it (REQ-TST-003): what changed since judges none
        of it, so it is never refused; a row of a run no longer shown is dropped."""
        if board_model != self.run_board_model or board_model != self.board_model or row not in self.rows:
            return
        self.preview_verdict.setText(theme.verdict_label(row["ai_result"]))
        self.preview_verdict.setStyleSheet(theme.verdict_style(row["ai_result"], big=False))
        self.view.set_image(image)

    def _show_preview(self, path: str, res: InspectionResult, board_model: str, run: JudgedBy | None) -> None:
        if board_model != self.run_board_model or board_model != self.board_model:
            return  # the run went with a board model change while this row was inspected (#180)
        if run is not self.run_judged:  # or a new run replaced it (#250)
            return
        if (changed := self._judged_now()) is not None:  # an AI model trained or activated while it was inspected
            self._refuse_preview(path, changed)  # neither shows nor reaches Compare (#250)
            self._note(changed)
            return
        self.preview_verdict.setText(theme.verdict_label(res.verdict))
        self.preview_verdict.setStyleSheet(theme.verdict_style(res.verdict, big=False))
        self.view.set_image(res.image)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(d.x, d.y, d.w, d.h, theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR), f"{d.no} {d.type}")
        self.shell.last_inspected = (path, res, None)  # a preview is not recorded

    def on_board_model_changed(self, name: str | None) -> None:
        self._fill_sources()
        self._fill_history()
        if self.run_board_model not in (None, name):  # another board model's run is not shown, previewed or reported
            self._clear_run()  # under this one's name (#180)

    def _clear_run(self) -> None:
        self.rows, self.metrics, self.run_folder, self.run_board_model, self.run_judged = [], {}, "", None, None
        self.run_note.hide()
        for t in self.tiles.values():
            t.set(None)
        self.confusion.clear()
        fill_table(self.table, [])
        self._clear_preview()
        self.btn_run.setText(self.tr("Run Test"))

    def on_show(self) -> None:
        bm = self.board_model
        if self.btn_run.isEnabled():  # a version frozen or locked on Training since; never in the middle of a run
            self._fill_sources()
        # An AI model trained or activated, a recipe saved or a Golden board set on another page (#250): the note says
        # so, and the pane drops the row previewed before; a row still selected is refused, as selecting it now would be
        changed = self._judged_now() if self.rows else None
        self._note(changed)
        if changed is not None and not any(r.get("overlay") for r in self.rows):  # a stored overlay is never refused
            self._drop_preview()
            self._clear_preview()
            if sel := self.table.selectionModel().selectedRows():
                self._refuse_preview(cell_item(self.table, sel[0].row(), 0).toolTip(), changed)
        elif not self.preview_empty.isHidden():  # what judged the run is in use again (an activation undone): the row
            self._clear_preview()  # still selected is previewed again, by it, in place of the refusal
            self._preview()
        if self.rows:
            self.empty.hide()
        elif not bm:
            self.empty.show_state(*self.no_board_model())
        elif not self.ctx.active_model(bm):
            heading = self.tr("No AI model for {board_model} yet").format(board_model=bm)
            self.empty.show_state(heading, *self.empty_step(self.tr("Train one on Training."), "Training"))
        else:
            what = self.tr("Select a folder with ok/ and ng/ sub-folders, then press Run Test.")
            heading = self.tr("No validation run for {board_model} yet").format(board_model=bm)
            self.empty.show_state(heading, what, self.tr("Select Test Folder…"), self.pick)

    def export_csv(self) -> None:
        if not self.rows:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export CSV"), str(self.ctx.settings.exports_dir / "model_test.csv"), self.tr("CSV (*.csv)")
        )
        if f:
            self.ctx.export_csv(f, self.rows, "test results")

    def export_report(self) -> None:
        if not self.rows:
            return
        f, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export report"),
            str(self.ctx.settings.exports_dir / "model_test_report.pdf"),
            self.tr("PDF (*.pdf)"),
        )
        if not f or self.run_board_model is None:
            return
        doc = QTextDocument()
        doc.setHtml(self._report_html())
        buf = QBuffer()  # rendered in memory, then written whole or not at all by the service layer (#180)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        w = QPdfWriter(buf)
        page = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(15, 15, 15, 15)
        )
        w.setPageLayout(page)
        doc.print_(w)
        del w
        run = self.rows[0]
        try:
            self.ctx.export_report(
                f, bytes(buf.data().data()), self.run_board_model, run.get("run_uuid"), run.get("model_version")
            )
        except AoiError as e:  # AOI-LOG-002 (not written) or AOI-USR-001 (role): no "Report saved"
            self.error(e)
            return
        self.shell.status(self.tr("Report saved: {file}").format(file=f))

    def _report_html(self) -> str:
        """The validation report: every sentence through tr(), the markup and the numbers from the code."""
        m = self.metrics
        bm = self.run_board_model or ""  # the board model the run was for (#180)
        run = self.rows[0] if self.rows else {}  # each row names the run and the AI model active then (REQ-SET-017)
        title = self.tr("AI Model Validation Report")
        head = self.tr(
            "Board model: <b>{board_model}</b> · AI model: {version} · Date: {date}<br>Validation folder: {folder}"
            "<br>Validation run UUID: {run_uuid} · AI model UUID: {model_uuid}"
        )
        head = head.format(
            board_model=html.escape(bm),
            version=html.escape(run.get("model_version") or self.tr("none")),
            date=f"{datetime.now():%Y-%m-%d %H:%M}",
            folder=html.escape(self.run_folder),
            run_uuid=run.get("run_uuid") or "—",
            model_uuid=run.get("model_uuid") or self.tr("none"),
        )
        off = self.tr(
            "The recipe turned the AI check off for this run: no AI model judged the images, and the verdicts come from"
            " the Golden board comparison alone."
        )
        head += f"<br>{html.escape(off)}" if run.get("ai_check") == "OFF" else ""  # the AI model named did not (#246)
        tiles = "".join(f"<th>{t.name}</th>" for t in self.tiles.values())
        rates = m.get("rates") or stats.validation_rates(self.rows)
        values = "".join(f"<td>{html.escape(phrase_text(stats.text(rates[k])))}</td>" for k in self.tiles)
        counts = self.tr("TP {tp} · FN {fn} · FP {fp} · TN {tn} (NG = positive class; WARN counted as NG)")
        counts = counts.format(tp=m["TP"], fn=m["FN"], fp=m["FP"], tn=m["TN"])
        headers = "".join(f"<th>{h}</th>" for h in self.headers)
        rows = "".join(
            f"<tr style='color:{theme.NG_COLOR if r['pass_fail'] == 'FAIL' else theme.PRINT_TEXT}'>"
            f"<td>{html.escape(Path(r['image']).name)}</td><td>{r['gt']}</td>"
            f"<td>{theme.verdict_label(r['ai_result'])}</td><td>{r['score']}</td>"
            f"<td>{html.escape(self._matches(r))}</td></tr>"
            for r in self.rows
        )
        return (
            f"<h2>{title}</h2><p>{head}</p>"
            f"<table border=1 cellpadding=4 cellspacing=0><tr>{tiles}</tr><tr>{values}</tr></table>"
            f"<p>{counts}</p>"
            f"<table border=1 cellpadding=3 cellspacing=0><tr>{headers}</tr>{rows}</table>"
        )
