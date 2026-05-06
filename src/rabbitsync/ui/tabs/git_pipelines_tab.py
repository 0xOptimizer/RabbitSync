"""Git & Pipelines tab — three-pane horizontal split."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core import git_graph as graph_mod
from rabbitsync.core import git_info
from rabbitsync.core.git_resolve import GitContext
from rabbitsync.ui import icons
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography
from rabbitsync.ui.widgets.log_graph_view import LogGraphView


class GitPane(QFrame):
    """One git column (used twice — source and copy)."""

    def __init__(
        self,
        title: str,
        *,
        on_action: Callable[[str], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self._theme = theme
        self._on_action = on_action

        self.setStyleSheet(
            f"QFrame {{ background-color: {palette.bg}; "
            f"border-right: 1px solid {palette.border}; }}"
        )

        self._title_label = QLabel(title, self)
        self._title_label.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )

        self._branch_label = QLabel("(no git context)", self)
        self._branch_label.setStyleSheet(
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; "
            f"color: {palette.fg};"
        )

        self._summary_label = QLabel("", self)
        self._summary_label.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg_muted};"
        )

        self._graph = LogGraphView(theme=theme, parent=self)

        # Single Actions ▾ dropdown — replaces a row of seven buttons.
        self._actions_btn = QToolButton(self)
        self._actions_btn.setText("Actions")
        self._actions_btn.setMinimumHeight(22)
        self._actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._actions_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._actions_btn.setIcon(icons.Icons.branch())
        menu = QMenu(self._actions_btn)
        for label, icon_fn, key in [
            ("Quick Push (stage + commit + push)", icons.Icons.push, "quick_push"),
            (None, None, None),
            ("Fetch", icons.Icons.fetch, "fetch"),
            ("Pull (ff-only)", icons.Icons.pull, "pull"),
            ("Push", icons.Icons.push, "push"),
            ("Stage…", icons.Icons.stage, "stage"),
            ("Commit…", icons.Icons.commit, "commit"),
            ("Branch…", icons.Icons.branch, "branch"),
            ("Stash…", icons.Icons.stash, "stash"),
        ]:
            if label is None:
                menu.addSeparator()
                continue
            act = QAction(icon_fn(), label, menu)
            act.triggered.connect(lambda _checked=False, k=key: self._on_action(k))
            menu.addAction(act)
        self._actions_btn.setMenu(menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(self._title_label)
        layout.addWidget(self._branch_label)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._graph, 1)
        layout.addWidget(self._actions_btn)

    def show_no_git(self) -> None:
        self._branch_label.setText("(no git repo detected at this folder or any ancestor)")
        self._summary_label.setText("")
        self._actions_btn.setEnabled(False)
        self._graph.setModel(None)

    def show_git(self, ctx: GitContext) -> None:
        status = git_info.status(ctx)
        if status is None:
            self.show_no_git()
            return
        ahead = status.ahead
        behind = status.behind
        branch = status.branch or "(detached)"
        self._branch_label.setText(f"{branch}  +{ahead} / -{behind}")
        if status.is_clean:
            summary = "clean"
        else:
            summary = (
                f"{status.modified_count} modified, "
                f"{status.added_count} added, "
                f"{status.deleted_count} deleted, "
                f"{status.untracked_count} untracked"
            )
        self._summary_label.setText(summary)
        self._actions_btn.setEnabled(True)
        self._graph.set_layout(graph_mod.build(ctx, limit=200))


class PipelinesPane(QFrame):
    """Right pane in Git & Pipelines tab — list of pipelines with per-row dropdowns."""

    HEADERS = ("Pipeline", "Last result", "")

    def __init__(
        self,
        *,
        on_run: Callable[[int], None],
        on_edit: Callable[[int], None],
        on_new: Callable[[], None],
        on_delete: Callable[[int], None],
        on_set_pre: Callable[[int], None],
        on_set_post: Callable[[int], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self._on_run = on_run
        self._on_edit = on_edit
        self._on_new = on_new
        self._on_delete = on_delete
        self._on_set_pre = on_set_pre
        self._on_set_post = on_set_post
        self.setStyleSheet(f"QFrame {{ background-color: {palette.bg}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        title = QLabel("Pipelines", self)
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )
        layout.addWidget(title)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(self.HEADERS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background-color: {palette.bg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"color: {palette.fg}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; }}"
        )
        layout.addWidget(self._tree, 1)

        self._empty = QLabel("No pipelines defined for this pair.", self)
        self._empty.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg_muted};"
        )
        layout.addWidget(self._empty)

        new_btn = QPushButton("+ New Pipeline…", self)
        new_btn.setIcon(icons.Icons.edit())
        new_btn.setMinimumHeight(22)
        new_btn.clicked.connect(self._on_new)
        layout.addWidget(new_btn)

    def populate(self, rows: list[dict]) -> None:
        """Each row: ``{id, name, last_status, last_when}``."""
        self._tree.clear()
        if not rows:
            self._empty.show()
            return
        self._empty.hide()
        for row in rows:
            it = QTreeWidgetItem([
                str(row.get("name", "")),
                f"{row.get('last_status') or '—'} {row.get('last_when') or ''}".strip(),
                "",
            ])
            it.setData(0, Qt.ItemDataRole.UserRole, int(row["id"]))
            self._tree.addTopLevelItem(it)
            self._install_row_actions(it, int(row["id"]))

    def _install_row_actions(self, item: QTreeWidgetItem, pipeline_id: int) -> None:
        wrapper = QFrame(self._tree)
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        run_btn = QPushButton("Run", wrapper)
        run_btn.setIcon(icons.Icons.run())
        run_btn.setIconSize(QSize(12, 12))
        run_btn.setFixedHeight(20)
        run_btn.clicked.connect(lambda: self._on_run(pipeline_id))
        h.addWidget(run_btn)

        more = QToolButton(wrapper)
        more.setText("▾")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setFixedHeight(20)
        menu = QMenu(more)
        for label, handler in [
            ("Edit steps…", lambda: self._on_edit(pipeline_id)),
            ("Set as pre-sync", lambda: self._on_set_pre(pipeline_id)),
            ("Set as post-sync", lambda: self._on_set_post(pipeline_id)),
            ("Delete pipeline", lambda: self._on_delete(pipeline_id)),
        ]:
            act = QAction(label, menu)
            act.triggered.connect(handler)
            menu.addAction(act)
        more.setMenu(menu)
        h.addWidget(more)

        self._tree.setItemWidget(item, 2, wrapper)


class GitPipelinesTab(QFrame):
    """The full tab body — Source git | Copy git | Pipelines."""

    def __init__(
        self,
        *,
        on_git_action: Callable[[str, str], None],
        on_pipeline_run: Callable[[int], None],
        on_pipeline_edit: Callable[[int], None],
        on_pipeline_new: Callable[[], None],
        on_pipeline_delete: Callable[[int], None],
        on_pipeline_set_pre: Callable[[int], None],
        on_pipeline_set_post: Callable[[int], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setStyleSheet(f"QFrame {{ background-color: {palette.bg}; }}")

        self._source_pane = GitPane(
            "Source",
            on_action=lambda key: on_git_action("source", key),
            theme=theme,
        )
        self._copy_pane = GitPane(
            "Copy",
            on_action=lambda key: on_git_action("copy", key),
            theme=theme,
        )
        self._pipelines = PipelinesPane(
            on_run=on_pipeline_run,
            on_edit=on_pipeline_edit,
            on_new=on_pipeline_new,
            on_delete=on_pipeline_delete,
            on_set_pre=on_pipeline_set_pre,
            on_set_post=on_pipeline_set_post,
            theme=theme,
        )

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._source_pane)
        splitter.addWidget(self._copy_pane)
        splitter.addWidget(self._pipelines)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)

    def show_contexts(self, *, source: GitContext, copy: GitContext) -> None:
        if source.has_git:
            self._source_pane.show_git(source)
        else:
            self._source_pane.show_no_git()
        if copy.has_git:
            self._copy_pane.show_git(copy)
        else:
            self._copy_pane.show_no_git()

    def set_pipelines(self, rows: list[dict]) -> None:
        self._pipelines.populate(rows)


__all__ = ["GitPane", "GitPipelinesTab", "PipelinesPane"]


_ = Path
