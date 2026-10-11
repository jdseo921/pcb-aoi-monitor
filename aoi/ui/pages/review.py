"""The review of an NG or WARN board on the line (REQ-INSP-013, ADR 0013): Real defect or False call.

One bar, shared by Inspection (the board just inspected) and Logs & Export (the record selected): a line saying where
the review stands and two buttons with their keys, F10 Real defect and F11 False call…. A False call asks for its
reason from a short list, which the user may also type over. The verdict the board was given never changes: the review
stands beside it, saved and audited by `AppContext.review_result` on the pool thread (REQ-SET-021).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QVBoxLayout, QWidget

from ...core.inspector import NG, WARN
from ...core.services import DEFECT, FALSE_CALL
from ..workers import Worker, start
from .base import QT_TRANSLATE_NOOP, Page, action_button, size_class

# The reasons a False call offers first, the commonest causes of an AOI false call; any other may be typed.
FALSE_CALL_REASONS = (
    QT_TRANSLATE_NOOP("Review", "Normal variation: the board is good"),
    QT_TRANSLATE_NOOP("Review", "Dust or debris on the board, not a defect"),
    QT_TRANSLATE_NOOP("Review", "Glare or lighting in the image"),
    QT_TRANSLATE_NOOP("Review", "Board out of position in the image"),
    QT_TRANSLATE_NOOP("Review", "Marking or label, not a defect"),
)


def tr(text: str) -> str:
    """A phrase marked QT_TRANSLATE_NOOP("Review", …), in the UI language."""
    return QCoreApplication.translate("Review", text)


def review_text(review: str | None) -> str:
    """The review in a word or two, for the Logs table and the bar: Real defect, False call or nothing."""
    if review == DEFECT:
        return QCoreApplication.translate("Review", "Real defect")
    if review == FALSE_CALL:
        return QCoreApplication.translate("Review", "False call")
    return ""


class ReviewBar(QWidget):
    """The review line and its two buttons. `page` owns the keys (F10, F11), live while it is shown; `on_saved` gets
    the record as saved, so the page shows it at once."""

    def __init__(self, page: Page, on_saved: Callable[[dict[str, Any]], None], compact: bool = False) -> None:
        """`compact`: the line and the buttons in one row, the line naming a review once there is one (Logs & Export,
        where the table's Review column already asks); else the line above the buttons (Inspection)."""
        super().__init__()
        self.page, self.on_saved, self.compact = page, on_saved, compact
        self.record: dict[str, Any] | None = None  # id, result and the review fields of the board shown
        self.saving: Worker | None = None
        self.act_defect = page.action(
            QCoreApplication.translate("Review", "Real defect"), "F10", lambda: self.store_review(DEFECT)
        )
        self.act_false = page.action(QCoreApplication.translate("Review", "False call…"), "F11", self.ask_false_call)
        layout = QHBoxLayout(self) if compact else QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.line = QLabel("")
        self.line.setWordWrap(not compact)
        layout.addWidget(self.line)
        row = QHBoxLayout()
        self.btn_defect = size_class(action_button(self.act_defect), "T")
        self.btn_false = size_class(action_button(self.act_false), "T")
        row.addWidget(self.btn_defect)
        row.addWidget(self.btn_false)
        layout.addLayout(row)
        self.show_record(None)

    def show_record(self, record: dict[str, Any] | None) -> None:
        """The board to review: a record with `id`, `result` and its review fields, or None. Only an NG or WARN board
        is reviewed; for any other the bar says nothing and its keys do nothing."""
        self.record = record
        can = record is not None and record.get("result") in (NG, WARN)
        self.line.setText(self._line(record) if can and record is not None else "")
        self.update_actions()

    def update_actions(self) -> None:
        can = self.record is not None and self.record.get("result") in (NG, WARN) and self.saving is None
        self.act_defect.setEnabled(can)
        self.act_false.setEnabled(can)

    def _line(self, record: dict[str, Any]) -> str:
        if not record.get("review") and self.compact:
            return ""
        if not record.get("review"):
            return QCoreApplication.translate(
                "Review", "Review this call: is the defect real? Real defect F10 · False call F11"
            )
        word = review_text(record["review"])
        if record.get("review_reason"):
            line = QCoreApplication.translate("Review", "Reviewed: {review} ({reason}) by {user}")
            return line.format(review=word, reason=record["review_reason"], user=record.get("review_by") or "")
        return QCoreApplication.translate("Review", "Reviewed: {review} by {user}").format(
            review=word, user=record.get("review_by") or ""
        )

    def ask_false_call(self) -> None:
        """F11: the reason first, from the list or typed; Cancel or an empty reason saves nothing."""
        if self.record is None:
            return
        items = [tr(r) for r in FALSE_CALL_REASONS]
        current = self.record.get("review_reason") if self.record.get("review") == FALSE_CALL else None
        index = items.index(current) if current in items else 0
        reason, ok = QInputDialog.getItem(
            self,
            QCoreApplication.translate("Review", "False call"),
            QCoreApplication.translate("Review", "Why is this call false? Pick a reason or type one."),
            items,
            index,
            True,
        )
        if ok and reason.strip():
            self.store_review(FALSE_CALL, reason.strip())

    def store_review(self, review: str, reason: str | None = None) -> None:
        """Save the review on the pool thread as the user shown now; the bar shows it when it is stored, and a refusal
        (AOI-INSP-015, AOI-USR-001, a database error) shows as the coded dialog."""
        if self.record is None or self.saving is not None:
            return
        w = self.saving = Worker(self.page.ctx.review_result, int(self.record["id"]), review, reason)

        def saved(record: dict[str, Any]) -> None:
            if self.record is not None and self.record.get("id") == record["id"]:
                self.show_record(record)
            self.on_saved(record)

        def finished() -> None:
            self.saving = None
            self.update_actions()

        w.signals.result.connect(saved)
        w.signals.error.connect(self.page.error)
        w.signals.finished.connect(finished)
        self.update_actions()
        start(w, self.page.ctx.jobs)
