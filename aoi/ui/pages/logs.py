"""Log & Export Screen (spec 4.4)."""

from __future__ import annotations

import dataclasses
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QCoreApplication, QDate, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.inspector import ai_check
from ...core.services import FALSE_CALL, NOT_REVIEWED, REVIEW_FILTERS, AppContext, CsvFile, HistoryFilter
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.flow import FlowLayout, labelled
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import (
    QT_TRANSLATE_NOOP,
    Page,
    WrappedLine,
    button,
    fill_table,
    make_table,
    row_key,
    size_class,
    view_text,
)
from .review import ReviewBar, review_text

# The columns of the checks file beside the records file (REQ-INSP-012), the header even when no record has checks;
# ai_check says whether the AI check ran on the record: RAN, OFF or NO_AI_MODEL (`inspector.ai_check`, #246).
CHECK_COLUMNS = [
    "inspection_id", "inspection_uuid", "time", "board_model", "view", "model_version", "model_uuid", "recipe_rev",
    "recipe_uuid", "ai_check", "no", "region", "metric", "source", "value", "threshold", "rule", "result",
]  # fmt: skip

DEFAULT_DAYS = 7  # a new page and Reset Filters show the last 7 days
VERDICTS = ("OK", "NG", "WARN")  # the Result filter's verdicts after All, as the sketch lists them
REVIEW_COLUMN = 4  # the table's Review column, after Result (REQ-INSP-013)
RECORDS_TAB, TYPES_TAB = 0, 1  # the page's tabs: the records with the selected one's overlay, their defects by type
BAR_COLUMN = 7  # the Defect types tab's last column, after Share: the bar of the type's defects (`ShareBar`)

if TYPE_CHECKING:
    from ..main_window import MainWindow


class NameFilter(QComboBox):
    """A Board model or Operator filter, as wide as its longest name where there is room (AdjustToContents). Qt
    resizes such a list to its size hint 20 ms after its names change, outside the layout, which lays it out at least
    as wide as its minimum size hint: the list was drawn 29 px narrower than its place, with a gap beside it, until the
    page was laid out again, so the same page showed two widths (#386's CI). Its size hint is never narrower than that
    minimum, so the resize keeps the width the layout gives it."""

    def sizeHint(self) -> QSize:
        return super().sizeHint().expandedTo(self.minimumSizeHint())


class ShareBar(QStyledItemDelegate):
    """The bar beside a Defect types row's Share, as long as the type's defects against the most any type has,
    SHARE_BAR_W at most, so the table reads as a Pareto chart (REQ-LOG-008) without Qt Charts, which is not LGPL. It
    has a column of its own with no text: drawn in the Share cell beside the number, it filled more of the cell than the
    cell's ground and was read as the ground of the text, white on the accent at 3.7:1 in the presenter theme (#390's
    CI). The bar's length is the row's key (`fill_table`); its colour is the theme's accent, read as it is drawn, which
    reads on the table's rows at 3:1 or more in both themes, as a graphic must (WCAG 1.4.11)."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        return QSize(theme.SHARE_BAR_W + 2 * theme.CELL_PAD, super().sizeHint(option, index).height())

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().paint(painter, option, index)  # the cell's ground
        length = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(length, float):
            return
        rect: QRect = option.rect
        cell = rect.adjusted(theme.CELL_PAD, theme.CELL_PAD, -theme.CELL_PAD, -theme.CELL_PAD)
        width = round(cell.width() * length)
        if width > 0:
            painter.fillRect(QRect(cell.left(), cell.top(), width, cell.height()), QColor(theme.ACCENT))


class LogsPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Logs & Export")
    role_notes = (  # each control below is greyed for a role that may not use it, never hidden (REQ-USR-001)
        (
            QT_TRANSLATE_NOOP("LogsPage", "Exports and Delete Records… need the {roles} role."),
            ("export_csv_files", "export_overlays", "delete_inspections"),
        ),
        (
            QT_TRANSLATE_NOOP("LogsPage", "Archive and Add to Training as OK need the {roles} role."),
            ("archive_old", "add_false_call_sample"),
        ),
    )

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.rows: list[dict[str, Any]] = []
        self.listed = HistoryFilter()  # the filter that listed `rows`, which an export audits (REQ-LOG-002)
        f = FlowLayout()  # one row at 1920 px, two where the page is narrower (REQ-LOG-009)
        self.d_from = QDateEdit(QDate.currentDate().addDays(-DEFAULT_DAYS))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")  # ISO dates everywhere (REQ-SET-017), not the locale's short form
            d.setDateRange(QDate(2000, 1, 1), QDate(2100, 12, 31))  # days every station's clock converts (#174)
        self.restyle()
        self.model = NameFilter()
        self.operator = NameFilter()
        for names in (self.model, self.operator):  # wide as their names where there is room; cut off in a narrow window
            names.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            names.setMinimumWidth(theme.FILTER_MIN_W)  # rather than hold it past 1600 px with the Result filter
        self.result = QComboBox()  # the verdict, All first (REQ-LOG-001)
        self.result.addItem(self.tr("All"), None)
        for verdict in VERDICTS:
            self.result.addItem(theme.verdict_label(verdict), verdict)
        # the review on the line, All first: the false calls alone, the real defects, or the NG and WARN records no one
        # has reviewed yet (REQ-LOG-009, ADR 0013)
        self.review_filter = QComboBox()
        self.review_filter.addItem(self.tr("All"), None)
        for review in REVIEW_FILTERS:
            name = self.tr("Not reviewed") if review == NOT_REVIEWED else review_text(review)
            self.review_filter.addItem(name, review)
        self.archived = QCheckBox(self.tr("Include archived"))
        fields = (
            (self.tr("From"), self.d_from),
            (self.tr("To"), self.d_to),
            (self.tr("Board model"), self.model),
            (self.tr("Operator"), self.operator),
            (self.tr("Result"), self.result),
            (self.tr("Review"), self.review_filter),
        )
        for label, w in fields:
            f.addWidget(labelled(label, w))
        f.addWidget(self.archived)
        f.addWidget(button(self.tr("Filter"), "primary", self.refresh))
        self.root.addLayout(f)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = make_table(
            [
                self.tr("Time"),
                self.tr("Board model"),
                self.tr("AI model"),
                self.tr("Result"),
                self.tr("Review"),
                self.tr("Defects"),
                self.tr("Operator"),
                self.tr("View"),
                self.tr("Recipe rev"),
                self.tr("Image"),
            ]
        )
        self.table.verticalHeader().setDefaultSectionSize(theme.TARGET_H)  # a history row is an operator target
        self.table.itemSelectionChanged.connect(self._preview)
        self.table.activated.connect(lambda _index: self.open_in_compare())  # Enter or a double-click on a row
        self.empty = EmptyState(self.table)
        self.busy = BusyOverlay(self.table, self.tr("Exporting…"))
        self.busy_delete = BusyOverlay(self.table, self.tr("Deleting…"))
        self.loading = BusyOverlay(self.table, self.tr("Loading records…"))
        self.listing: Worker | None = None  # the records being read for the page shown, if they are (`list_records`)
        split.addWidget(self.table)
        self.view = ImageView(placeholder=self.tr("Select a row to see its overlay"))
        split.addWidget(self.view)
        split.setSizes([1100, 500])  # the nine columns of the sketch, the image name cut short at 1920 px
        # The records, and their defects by type, most first: the defect Pareto of an AOI line's reports, with the
        # false calls by type beside it (REQ-LOG-008), on the page's whole width
        self.tabs = QTabWidget()
        self.tabs.addTab(split, self.tr("Records"))
        self.tabs.addTab(self._types_tab(), self.tr("Defect types"))
        self.tabs.currentChanged.connect(lambda _index: self.count_types())
        self.root.addWidget(self.tabs, 1)

        # the counts, and the selected record's way to Compare (the Logs sketch); the buttons on a line of their own,
        # at its right, where the page is too narrow for both (#104)
        line = FlowLayout(gap=theme.ROW_GAP, right=True)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        line.add_stretched(self.summary)
        # The selected NG or WARN record's review, F10 Real defect and F11 False call, as on Inspection (REQ-INSP-013)
        self.review = ReviewBar(self, self._reviewed, compact=True)
        line.addWidget(self.review)
        # a board reviewed as a false call into Training as an OK sample, the Engineer's and Admin's (REQ-TRN-020)
        self.btn_train = size_class(button(self.tr("Add to Training as OK"), slot=self.add_to_training), "T")
        line.addWidget(self.btn_train)
        self.btn_compare = size_class(button(self.tr("Open in Compare ›"), slot=self.open_in_compare), "T")
        line.addWidget(self.btn_compare)
        self.root.addLayout(line)
        b = FlowLayout(gap=theme.ROW_GAP, right=True)  # at the page's right, on two lines where it is narrow (#104)
        self.btn_csv = button(self.tr("Export CSV"), slot=self.export_csv)
        self.btn_img = button(self.tr("Export Image Overlays"), slot=self.export_overlays)
        self._arch_days = ctx.settings.log_retention_days  # the day count the button shows and archives by (#201)
        self.btn_arch = button(self._archive_text(), slot=self.archive)
        # red, the Admin's alone, last in its row and never the default (REQ-LOG-003, REQ-SET-018)
        self.btn_delete = button(self.tr("Delete Records…"), "danger", self.delete_records)
        for x in (self.btn_csv, self.btn_img, self.btn_arch, self.btn_delete):
            b.addWidget(x)
        self.root.addLayout(b)

    def _types_tab(self) -> QWidget:
        """The Defect types tab: a note on what it counts, over the table `count_types` fills."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, theme.SPACE_S, 0, 0)
        note = self.tr(
            "The listed records' defects by type, most first. Records: the records holding the type; Reviewed and"
            " False calls: those of them reviewed on the line, and reviewed as a false call."
        )
        line = WrappedLine(note)
        line.setContentsMargins(theme.SPACE_S, 0, theme.SPACE_S, 0)  # clear of the tab's frame
        layout.addWidget(line)
        headers = [
            self.tr("Defect type"), self.tr("Defects"), self.tr("Records"), self.tr("Reviewed"), self.tr("False calls"),
            self.tr("Cumulative"), self.tr("Share"), "",  # the bar, beside Share, needs no heading of its own
        ]  # fmt: skip
        self.type_table = make_table(headers, sortable=False)  # most first is the order it is read in
        self.type_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)  # nothing to do with a row
        self.type_table.setItemDelegateForColumn(BAR_COLUMN, ShareBar(self.type_table))
        # the bar's column sized as the others, to its contents (`ShareBar.sizeHint`): a stretched last section is sized
        # to its text when the rows are filled, which left no room for a bar
        self.type_table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.type_table, 1)
        self.types_empty = EmptyState(self.type_table)
        self.counting_types = BusyOverlay(self.type_table, self.tr("Counting defects…"))
        self.counting: Worker | None = None  # the defects being counted for the tab, if they are (`count_types`)
        return tab

    def refresh(self) -> None:
        """Filter, Reset Filters, Show All Records, Archive and a delete: the records the filter lists, read and shown
        at once. A listing the page started when it was shown is dropped: this one is newer."""
        self._drop_listing()
        listed = self._filter()
        rows = self.ctx.inspections(**dataclasses.asdict(listed))
        self.listed = listed
        self.show_rows(rows)

    def _filter(self) -> HistoryFilter:
        """The filter in the boxes, as `AppContext.inspections` takes it: local dates, board model, operator, result,
        archived or not, and review; the exports and Delete Records… audit it (REQ-LOG-002, REQ-LOG-003)."""
        return HistoryFilter(
            self.d_from.date().toString("yyyy-MM-dd"),
            self.d_to.date().toString("yyyy-MM-dd"),
            self.model.currentData(),
            self.operator.currentData(),
            self.result.currentData(),
            self.archived.isChecked(),
            self.review_filter.currentData(),
        )

    def list_records(self) -> None:
        """The page shown: the records the filter lists are read on the pool thread and shown when they arrive, so the
        page is up at once (REQ-SET-020). At 100,000 records, reading the last 7 days on the UI thread held the switch
        to this page for 6.5 s (S55). `loading` covers the table meanwhile, from 1 s on with the seconds so far, and the
        exports and Delete Records… wait for the listing, so none of them takes the rows shown before. Filter, or the
        page shown again, drops it: the newest listing wins. Rows that arrive after another page is shown are dropped
        too, since filling the table then would hold that page, and this one lists again when shown."""
        self._drop_listing()
        listed = self._filter()
        w = self.listing = Worker(self.ctx.inspections, **dataclasses.asdict(listed))
        ref = weakref.ref(w)  # the slots hold the worker weakly, as Page.run_in_background's do (#132)

        def arrived(rows: list[dict[str, Any]]) -> None:
            if (worker := ref()) is not None and worker is self.listing and self.shell.stack.currentWidget() is self:
                self.listed = listed
                self.show_rows(rows)

        def failed(exc: BaseException) -> None:
            if (worker := ref()) is not None and worker is self.listing:
                self.error(exc)
            else:  # a listing dropped meanwhile shows nothing, but its error is logged (#206)
                self.ctx.report_error(exc, self.title)

        def finished() -> None:
            if (worker := ref()) is not None and worker is self.listing:
                self.listing = None
                self.loading.finish()
                self.update_actions()

        w.signals.result.connect(arrived)
        w.signals.error.connect(failed)
        w.signals.finished.connect(finished)
        self.loading.watch(w.job)
        self.update_actions()
        start(w, self.ctx.jobs)

    def _drop_listing(self) -> None:
        if self.listing is not None:
            self.listing.stop()  # a read cannot stop half-way: its rows arrive and are dropped
            self.listing = None
            self.loading.finish()
            self.update_actions()

    def show_rows(self, rows: list[dict[str, Any]]) -> None:
        """Show `rows`, the records the filter listed, with their summary, or the empty state that says why none are."""
        self.table.clearSelection()  # the preview follows the selection, so it clears now and never reads a row that
        # fill_table is replacing (#174): a selected row that survives a shrinking table still holds an old record's ID
        self.rows = rows
        fill_table(
            self.table,
            [
                [
                    to_local(r["time"]),
                    r["board_model"],
                    r["model_version"] or "",
                    theme.verdict_label(r["result"]),
                    review_text(r["review"]),
                    r["defect_count"],
                    r["operator"],
                    view_text(r["view"]) if r["view"] else "",  # rows from before migration 0005 recorded no view
                    r["recipe_rev"],
                    Path(r["image_path"]).name,
                ]
                for r in self.rows
            ],
            [theme.VERDICT_COLORS[r["result"]] if r["result"] != "OK" else None for r in self.rows],
            keys=[r["id"] for r in self.rows],
            color_column=3,  # the Result cell alone: a whole coloured row reads poorly at 14 pt (the Logs sketch)
        )
        n, span = len(self.rows), self.ctx.history_span()  # not every record: seconds at 100,000 (REQ-LOG-001)
        by = {v: sum(r["result"] == v for r in self.rows) for v in VERDICTS}
        counts = self.tr("{count:,} record(s) · OK {ok:,} of {count:,} ({rate:.1f} %) · NG {ng:,} · WARN {warn:,}")
        line = counts.format(count=n, ok=by["OK"], rate=100 * by["OK"] / max(n, 1), ng=by["NG"], warn=by["WARN"])
        archived = span["archived"] if span else 0
        line += self.tr(" · archived {archived:,}").format(archived=archived) if archived else ""
        reviewed = [r["review"] for r in self.rows if r["review"]]  # the reviews on the line (REQ-INSP-013)
        if reviewed:
            false_calls = reviewed.count("FALSE_CALL")
            line += self.tr(" · reviewed {reviewed:,}, false calls {false_calls:,}").format(
                reviewed=len(reviewed), false_calls=false_calls
            )
        self.summary.setText(line if n else self.tr("No records"))
        self.count_types()  # the Defect types tab, if it is shown, counts the records now listed
        if n:
            self.empty.hide()
        elif span:  # not every record: that took seconds at 100,000 (REQ-LOG-001)
            if self.ctx.inspections(*self._default_dates()):  # what Reset Filters would show
                todo = self.tr("Widen the dates or the filters."), self.tr("Reset Filters"), self.reset_filters
            else:  # Reset Filters would run the same empty query again (#200): the link shows every record instead
                oldest, newest = (to_local(span[k])[:10] for k in ("oldest", "newest"))  # local dates
                todo = (
                    self.tr("Every record is archived or older than {days} days.").format(days=DEFAULT_DAYS),
                    self.tr("Show All Records"),
                    lambda: self.show_all_records(oldest, newest, bool(span["archived"])),
                )
            self.show_empty(self.empty, self.tr("No records match"), *todo)
        else:
            step = self.empty_step(self.tr("Run boards on Inspection."), "Inspection")
            self.show_empty(self.empty, self.tr("No inspections yet"), *step)

    @staticmethod
    def _default_dates() -> tuple[str, str]:
        """From and To of a new page and of Reset Filters: the last 7 days to today, as local dates."""
        today = QDate.currentDate()
        return today.addDays(-DEFAULT_DAYS).toString("yyyy-MM-dd"), today.toString("yyyy-MM-dd")

    def reset_filters(self) -> None:
        self._set_filters(*self._default_dates(), archived=False)

    def show_all_records(self, oldest: str, newest: str, archived: bool) -> None:
        """Every record (#200): From the oldest record's local date to today, or to the newest record's date when the
        clock has gone back, every board model, operator, verdict and review, with archived records when there are
        any."""
        today = QDate.currentDate().toString("yyyy-MM-dd")
        self._set_filters(oldest, max(newest, today), archived)

    def _set_filters(self, date_from: str, date_to: str, archived: bool) -> None:
        self.d_from.setDate(QDate.fromString(date_from, "yyyy-MM-dd"))
        self.d_to.setDate(QDate.fromString(date_to, "yyyy-MM-dd"))
        self.model.setCurrentIndex(0)
        self.operator.setCurrentIndex(0)
        self.result.setCurrentIndex(0)
        self.review_filter.setCurrentIndex(0)
        self.archived.setChecked(archived)
        self.refresh()

    def _preview(self) -> None:
        """The selected record's overlay, or the placeholder: never another record's board (#174)."""
        iid = self._selected_id()
        r = next((x for x in self.rows if x["id"] == iid), None)  # None: a row no longer listed
        overlay = r["overlay_path"] if r else None
        self.view.set_image(self.ctx.load_image(overlay) if overlay and Path(overlay).exists() else None)
        self.btn_compare.setEnabled(r is not None)
        self.review.show_record(r)
        self.update_actions()  # Add to Training as OK follows the selected record's review

    def _reviewed(self, record: dict[str, Any]) -> None:
        """A review saved: the listed row and its Review cell show it at once, without listing again (REQ-INSP-013)."""
        keys = ("review", "review_reason", "review_by", "review_time")
        for r in self.rows:
            if r["id"] == record["id"]:
                r.update({k: record[k] for k in keys})
        column = REVIEW_COLUMN
        for row in range(self.table.rowCount()):
            if int(row_key(self.table, row)) == record["id"] and (item := self.table.item(row, column)) is not None:
                item.setText(review_text(record["review"]))
        self.count_types()  # a false call changes its types' false calls, if the tab is shown
        self.update_actions()  # and makes the board one to add to Training
        self.shell.status(
            self.tr("Review saved: {review} for record {record}.").format(
                review=review_text(record["review"]), record=record["id"]
            )
        )

    def count_types(self) -> None:
        """The Defect types tab shown: the listed records' defects counted by type on the pool thread (REQ-SET-020),
        again whenever the records listed or a review changes while it is shown; the newest count wins, and one
        dropped meanwhile shows nothing. A separate worker from the exports', which `run_in_background` would stop."""
        if self.tabs.currentIndex() != TYPES_TAB:
            return
        if self.counting is not None:
            self.counting.stop()  # a count cannot stop half-way: it arrives and is dropped
        ids = [r["id"] for r in self.rows]
        w = self.counting = Worker(self.ctx.defect_pareto, ids)
        ref = weakref.ref(w)  # the slots hold the worker weakly, as Page.run_in_background's do (#132)

        def arrived(types: list[dict[str, Any]]) -> None:
            if (worker := ref()) is not None and worker is self.counting:
                self.show_types(types, len(ids))

        def failed(exc: BaseException) -> None:
            if (worker := ref()) is not None and worker is self.counting:
                self.error(exc)
            else:  # a count dropped meanwhile shows nothing, but its error is logged (#206)
                self.ctx.report_error(exc, self.title)

        def finished() -> None:
            if (worker := ref()) is not None and worker is self.counting:
                self.counting = None
                self.counting_types.finish()

        w.signals.result.connect(arrived)
        w.signals.error.connect(failed)
        w.signals.finished.connect(finished)
        self.counting_types.watch(w.job)
        start(w, self.ctx.jobs)

    def show_types(self, types: list[dict[str, Any]], records: int) -> None:
        """Fill the Defect types tab with `AppContext.defect_pareto`'s rows for `records` listed records, or say why
        it has none."""
        tip = self.tr(
            "{type}: {defects:,} defect(s), {share:.1f} % of those listed, on {boards:,} record(s); {reviewed:,} of"
            " them reviewed, {false_calls:,} as a false call"
        )
        percent = self.tr("{percent:.1f} %")
        named = [t | {"type": t["type"] or self.tr("No type")} for t in types]
        most = max((t["defects"] for t in types), default=1)
        fill_table(
            self.type_table,
            [
                [
                    t["type"],
                    t["defects"],
                    t["boards"],
                    t["reviewed"],
                    t["false_calls"],
                    percent.format(percent=100 * t["cumulative"]),
                    percent.format(percent=100 * t["share"]),
                    None,  # the bar (`ShareBar`)
                ]
                for t in named
            ],
            tooltips=[tip.format(**(t | {"share": 100 * t["share"]})) for t in named],
            keys=[t["defects"] / most for t in types],  # the length of each bar, the most defects the longest
        )
        if types:
            self.types_empty.hide()
        elif records:
            sentence = self.tr("None of the {count:,} listed record(s) holds a defect.").format(count=records)
            self.types_empty.show_state(self.tr("No defects"), sentence)
        else:
            self.types_empty.show_state(self.tr("No records"), self.tr("Widen the dates or the filters."))

    def _selected_id(self) -> int | None:
        """The ID of the record of the first selected row, kept with the row as it sorts; None with none selected."""
        rows = self.table.selectionModel().selectedRows()
        return int(row_key(self.table, rows[0].row())) if rows else None

    def open_in_compare(self) -> None:
        """Open in Compare ›, Enter or a double-click: the selected record on Compare as it was decided, its failing
        checks marked (REQ-INSP-009; MainWindow.open_stored, #130)."""
        if (iid := self._selected_id()) is not None:
            self.shell.open_stored(iid)

    def _confirm(self, question: str, overwrites: bool = False) -> bool:
        """Yes to `question`; for one that `overwrites` a file, No is the default, so Enter keeps it (REQ-SET-018)."""
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        default = no if overwrites else yes  # Qt left the default to the focus, which fell on Yes (#182)
        return QMessageBox.question(self, self.tr("Confirm export"), question, yes | no, default) == yes

    def export_csv(self) -> None:
        question = self.tr(
            "Export CSV for {count} record(s)? Two files are written: the records, and a second file ending in"
            " _checks.csv with one row per check."
        )
        if not self.rows or not self._confirm(question.format(count=len(self.rows))):
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export CSV"), str(self.ctx.settings.exports_dir / "inspections.csv"), self.tr("CSV (*.csv)")
        )
        if not f:
            return
        checks_file = Path(f).with_name(f"{Path(f).stem}_checks.csv")
        if checks_file.exists() and not self._confirm(
            self.tr("{file} exists. Replace it?").format(file=checks_file.name), overwrites=True
        ):
            return
        self.run_in_background(
            self._write_csv, list(self.rows), f, checks_file, self.listed, with_progress=True, busy=self.busy,
            on_result=lambda counts: self._csv_written(counts, Path(f), checks_file),
            on_cancel=lambda counts: self._csv_written(counts, Path(f), checks_file),
        )  # fmt: skip

    def _write_csv(
        self,
        rows: list[dict[str, Any]],
        f: str,
        checks_file: Path,
        listed: HistoryFilter,
        progress: Callable[[int, int], None],
        should_stop: Callable[[], bool],
    ) -> tuple[int, int] | None:
        """Pool thread (REQ-SET-021, #194): gather each record's defects and checks, then write both files; (records,
        check rows), or None when Cancel came before the files were written, which leaves neither."""
        # Two files: the records, and beside them one row per check with the evidence that decided each verdict
        # (REQ-INSP-012). The records keep their columns in order, so a reader built on them still works.
        checks = self.ctx.checks_for_many([r["id"] for r in rows])
        out: list[dict[str, Any]] = []
        check_rows: list[dict[str, Any]] = []
        for i, r in enumerate(rows, 1):
            if should_stop():
                return None
            ds = self.ctx.defects_for(r["id"])
            ai = self._ai_check(r["id"])
            out.append(
                {
                    "id": r["id"],
                    "time": r["time"],
                    "board_model": r["board_model"],
                    "view": r["view"],
                    "model_version": r["model_version"],
                    "recipe_rev": r["recipe_rev"],
                    "result": r["result"],
                    "score": r["score"],
                    "defects": len(ds),
                    "defect_types": ";".join(sorted({d["type"] for d in ds})),
                    "operator": r["operator"],
                    "image": r["image_path"],
                    "overlay": r["overlay_path"],
                    "uuid": r["uuid"],
                    "model_uuid": r["model_uuid"],
                    "recipe_uuid": r["recipe_uuid"],
                    "ai_check": ai,  # after the columns before it, so they keep their places
                    "review": r["review"] or "",  # the review on the line, after them all (REQ-INSP-013)
                    "review_reason": r["review_reason"] or "",
                    "review_by": r["review_by"] or "",
                    "review_time": r["review_time"] or "",
                }
            )
            record = {k: r[k] for k in ("time", "board_model", "view", "model_version", "model_uuid", "recipe_rev")}
            record.update(recipe_uuid=r["recipe_uuid"], ai_check=ai)
            for c in checks[r["id"]]:
                evidence = {
                    k: c[k] for k in ("no", "region", "metric", "source", "value", "threshold", "rule", "result")
                }
                check_rows.append({"inspection_id": r["id"], "inspection_uuid": r["uuid"], **record, **evidence})
            progress(i, len(rows))
        # both files or neither (#195); one another program holds open is refused with AOI-LOG-002, shown as the dialog
        files = [CsvFile(f, out), CsvFile(checks_file, check_rows, "checks", CHECK_COLUMNS)]
        self.ctx.export_csv_files(files, listed)  # each entry holds the filter and the count (REQ-LOG-002)
        return len(out), len(check_rows)

    def _ai_check(self, inspection_id: int) -> str:
        """`inspector.ai_check` of a record's stored result, or "" when the record does not tell: none is stored, or the
        stored one cannot be read (damaged), which is logged by the record's id and stops no export (#246)."""
        try:
            return ai_check(self.ctx.inspection_result(inspection_id))
        except AoiError:  # AOI-CMP-002: not JSON, or JSON that is no stored result
            self.ctx.log.warning("export.result_not_read", exc_info=True, extra={"inspection_id": inspection_id})
            return ""

    def _csv_written(self, counts: tuple[int, int] | None, f: Path, checks_file: Path) -> None:
        if counts is None:
            self.shell.status(self.tr("Export CSV stopped: no file was written."))
            return
        status = self.tr("Exported {count} records and {checks} check rows to {folder}: {file}, {checks_file}")
        self.shell.status(
            status.format(count=counts[0], checks=counts[1], folder=f.parent, file=f.name, checks_file=checks_file.name)
        )

    def export_overlays(self) -> None:
        question = self.tr("Export overlay images for {count} record(s)?").format(count=len(self.rows))
        if not self.rows or not self._confirm(question):
            return
        d = QFileDialog.getExistingDirectory(self, self.tr("Export overlays to"), str(self.ctx.settings.exports_dir))
        if not d:
            return
        copied = self.tr("Copied {count} overlay image(s) to {folder}")
        stopped = self.tr("Stopped: copied {count} overlay image(s) to {folder}; the others were not copied.")
        # On the pool (REQ-SET-021, #194): Cancel keeps the overlays copied so far and says how many.
        self.run_in_background(
            self.ctx.export_overlays, list(self.rows), d, listed=self.listed, with_progress=True, busy=self.busy,
            on_result=lambda n: self.shell.status(copied.format(count=n, folder=d)),
            on_cancel=lambda n: self.shell.status(stopped.format(count=n or 0, folder=d)),
        )  # fmt: skip

    def _archive_text(self) -> str:
        return self.tr("Archive older than {days} days").format(days=self._arch_days)

    def archive(self) -> None:
        n = self.ctx.archive_old(self._arch_days)  # the number on the button, never another one
        self.shell.status(self.tr("Archived {count} record(s)").format(count=n))
        self.refresh()

    def restyle(self) -> None:
        """The calendars' weekend days in the theme's TEXT, not Qt's red, which reads at 4.1:1 on the dark calendar
        (#239); again when the theme is switched (REQ-SET-008)."""
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(theme.TEXT))
        for d in (self.d_from, self.d_to):
            for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
                d.calendarWidget().setWeekdayTextFormat(day, weekend)

    def delete_records(self) -> None:
        """Delete Records… (REQ-LOG-003, Q25): the records the filter lists, once a question naming their count is
        answered Yes (No is the default, REQ-SET-018) and a reason typed, which the audit trail keeps. The service
        refuses any role but the Admin's, and a blank reason (AOI-LOG-003); it runs on the pool (REQ-SET-021)."""
        n = len(self.rows)
        question = self.tr(
            "Delete {count} record(s) and their evidence files? This cannot be undone; the audit trail keeps who"
            " deleted them, when and why."
        ).format(count=n)
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        if not n or QMessageBox.question(self, self.tr("Delete Records"), question, yes | no, no) != yes:
            return
        ask = self.tr("Why are these {count} record(s) deleted?").format(count=n)
        reason, ok = QInputDialog.getText(self, self.tr("Delete Records"), ask)
        if not ok:
            return
        said = self.tr("Deleted {records} record(s) and {files} evidence file(s)")

        def deleted(counts: dict[str, int] | None) -> None:
            if counts is not None:
                self.shell.status(said.format(**counts))
            self.refresh()

        self.run_in_background(
            self.ctx.delete_inspections, [r["id"] for r in self.rows], self.listed, reason, busy=self.busy_delete,
            on_result=deleted, on_cancel=deleted, on_error=lambda _e: self.refresh(),
        )  # fmt: skip

    def update_actions(self) -> None:
        # one export or delete at a time, as a second would stop the first (#194), and none while the page is still
        # listing records, which would take the rows shown before (S55)
        # and each greyed, never hidden, for a role the service refuses, saying who may (REQ-USR-001): the exports and
        # Delete Records… are the Admin's, as customer results leave the station only by an Admin (Q58, #151)
        idle = self._bg is None and self.listing is None
        self.role_gate(self.btn_csv, "export_csv_files", idle)
        self.role_gate(self.btn_img, "export_overlays", idle)
        self.role_gate(self.btn_arch, "archive_old")
        self.btn_compare.setEnabled(bool(self.table.selectionModel().selectedRows()))
        self.role_gate(self.btn_delete, "delete_inspections", idle)
        selected = self._selected()
        false_call = selected is not None and selected["review"] == FALSE_CALL
        self.role_gate(self.btn_train, "add_false_call_sample", idle and false_call)

    def _selected(self) -> dict[str, Any] | None:
        """The listed record of the first selected row, or None."""
        iid = self._selected_id()
        return next((r for r in self.rows if r["id"] == iid), None)

    def add_to_training(self) -> None:
        """Add to Training as OK: the selected board, reviewed as a false call, becomes an OK sample of its board model
        in its view, on the pool thread (REQ-TRN-020). No confirmation: the sample can be deleted on Training."""
        r = self._selected()
        if r is None or r["review"] != FALSE_CALL:
            return
        record = r["id"]

        def added(out: dict[str, Any]) -> None:
            if out["added"]:
                said = self.tr("Record {record}'s board is now an OK sample of {board} ({view}) on Training.")
            else:
                said = self.tr("Record {record}'s board is already a sample of {board}, labelled {label}, on Training.")
            label = QCoreApplication.translate("TrainingPage", out["label"])  # OK, NG or UNSURE, as Training says it
            board, view = out["board_model"], view_text(out["view"])
            self.shell.status(said.format(record=record, board=board, view=view, label=label))

        self.run_in_background(self.ctx.add_false_call_sample, record, on_result=added)

    def show_board_model(self, name: str) -> None:
        """The history of board model `name` alone, as the first-run guide's Open Logs & Export › opens it (B5)."""
        self.model.setCurrentIndex(max(0, self.model.findData(name)))
        self.list_records()

    def on_show(self) -> None:
        self.update_actions()
        self._arch_days = self.ctx.settings.log_retention_days  # a retention saved on Settings applies at once (#201)
        self.btn_arch.setText(self._archive_text())
        for combo, values in (
            (self.model, self.ctx.board_models()),
            (self.operator, [u["name"] for u in self.ctx.users()]),
        ):
            cur = combo.currentData()
            combo.clear()
            combo.addItem(self.tr("All"), None)
            for v in values:
                combo.addItem(v, v)
            i = combo.findData(cur)
            combo.setCurrentIndex(max(0, i))
        self.list_records()
