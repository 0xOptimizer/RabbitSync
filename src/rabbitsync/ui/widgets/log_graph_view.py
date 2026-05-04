"""Custom QTableView that paints a real branched git log graph.

Column 0 is the graph column (painted by :class:`GraphDelegate`); columns
1-3 are commit subject, author, and author time. The model wraps a
:class:`GraphLayout`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from rabbitsync.core.git_graph import GraphLayout, GraphRow
from rabbitsync.ui.theme import DARK, LIGHT, Typography


_COL_GRAPH = 0
_COL_SUBJECT = 1
_COL_AUTHOR = 2
_COL_DATE = 3

# Lane spacing in pixels — controls graph density.
_LANE_PX = 18
# Commit-node radius.
_NODE_R = 4


class GraphLogModel(QAbstractTableModel):
    """Wraps a :class:`GraphLayout` for a QTableView."""

    HEADERS = ("Graph", "Subject", "Author", "Date")

    def __init__(self, layout: GraphLayout | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout: GraphLayout = layout or GraphLayout(rows=())

    def set_layout(self, layout: GraphLayout) -> None:
        self.beginResetModel()
        self._layout = layout
        self.endResetModel()

    def row(self, index: int) -> GraphRow:
        return self._layout.rows[index]

    @property
    def max_lane(self) -> int:
        if not self._layout.rows:
            return 0
        return max(r.lane for r in self._layout.rows)

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self._layout.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 4

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        if 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid():
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._layout.rows[index.row()]
        col = index.column()
        if col == _COL_SUBJECT:
            return row.commit.subject
        if col == _COL_AUTHOR:
            return row.commit.author
        if col == _COL_DATE:
            try:
                dt = datetime.fromtimestamp(row.commit.author_time, tz=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except (OSError, ValueError, OverflowError):
                return ""
        return None


class GraphDelegate(QStyledItemDelegate):
    """Paints the lane edges and commit node in column 0."""

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = DARK if theme == "dark" else LIGHT

    def sizeHint(self, _option: QStyleOptionViewItem, index: QModelIndex):  # noqa: ANN201
        model = index.model()
        if isinstance(model, GraphLogModel):
            width = (model.max_lane + 1) * _LANE_PX + 16
            return _qsize(width, 24)
        return _qsize(80, 24)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        if index.column() != _COL_GRAPH:
            super().paint(painter, option, index)
            return

        model = index.model()
        if not isinstance(model, GraphLogModel):
            super().paint(painter, option, index)
            return

        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Clip and translate to the cell.
            rect = option.rect
            painter.translate(rect.x(), rect.y())
            cell_w = rect.width()
            cell_h = rect.height()

            row = model.row(index.row())
            color = QColor(row.lane_color)

            # Draw incoming edges: from edge_in's from_lane center at row top
            # to to_lane center at row middle.
            mid_y = cell_h / 2
            for edge in row.edges_in:
                self._draw_edge(
                    painter,
                    from_x=_lane_x(edge.from_lane),
                    from_y=0,
                    to_x=_lane_x(edge.to_lane),
                    to_y=mid_y,
                    color=color if edge.to_lane == row.lane else QColor(self._palette.fg_muted),
                )
            # Outgoing edges: from row middle to next-row top.
            for edge in row.edges_out:
                self._draw_edge(
                    painter,
                    from_x=_lane_x(edge.from_lane),
                    from_y=mid_y,
                    to_x=_lane_x(edge.to_lane),
                    to_y=cell_h,
                    color=color if edge.from_lane == row.lane else QColor(self._palette.fg_muted),
                )

            # Draw the commit node.
            cx = _lane_x(row.lane)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(color)
            painter.drawEllipse(int(cx - _NODE_R), int(mid_y - _NODE_R), _NODE_R * 2, _NODE_R * 2)

            # Merge commits get a doubled outline.
            if len(row.commit.parents) >= 2:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(
                    int(cx - _NODE_R - 3), int(mid_y - _NODE_R - 3),
                    (_NODE_R + 3) * 2, (_NODE_R + 3) * 2,
                )

            # Tiny refs annotation if present (e.g. HEAD, branch, tag).
            if row.commit.refs:
                text_x = _lane_x(model.max_lane + 1) + 6
                painter.setPen(QPen(QColor(self._palette.fg_muted)))
                font = painter.font()
                font.setFamily(Typography.MONO_FAMILY.split(",")[0])
                font.setPointSize(Typography.MONO_PT - 1)
                painter.setFont(font)
                label = " ".join(row.commit.refs[:3])
                painter.drawText(
                    int(text_x), int(mid_y + 4),
                    label[: max(1, (cell_w - int(text_x)) // 7)],
                )
        finally:
            painter.restore()

    def _draw_edge(
        self,
        painter: QPainter,
        *,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        color: QColor,
    ) -> None:
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # Quadratic bezier — control point halfway between, on the row break.
        if from_x == to_x:
            painter.drawLine(int(from_x), int(from_y), int(to_x), int(to_y))
        else:
            from PySide6.QtGui import QPainterPath

            path = QPainterPath()
            path.moveTo(from_x, from_y)
            mid_y = (from_y + to_y) / 2
            path.cubicTo(from_x, mid_y, to_x, mid_y, to_x, to_y)
            painter.drawPath(path)


def _lane_x(lane: int) -> float:
    return (lane * _LANE_PX) + (_LANE_PX / 2)


def _qsize(w: int, h: int):  # noqa: ANN201
    from PySide6.QtCore import QSize

    return QSize(w, h)


class LogGraphView(QTableView):
    """Convenience: a QTableView pre-configured for the log graph."""

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        palette = DARK if theme == "dark" else LIGHT
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(_COL_GRAPH, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(_COL_SUBJECT, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(_COL_AUTHOR, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(_COL_DATE, QHeaderView.ResizeMode.ResizeToContents)
        self.setItemDelegateForColumn(_COL_GRAPH, GraphDelegate(theme=theme, parent=self))
        self.setStyleSheet(
            f"QTableView {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"selection-background-color: {palette.accent}; "
            f"selection-color: white; "
            f"border: none; }}"
        )

    def set_layout(self, layout: GraphLayout) -> None:
        model = GraphLogModel(layout, parent=self)
        self.setModel(model)
        self.setColumnWidth(_COL_GRAPH, max(80, (model.max_lane + 1) * _LANE_PX + 24))


__all__ = ["GraphDelegate", "GraphLogModel", "LogGraphView"]
