"""Real implementations of every git action exposed by the Actions ▾ menu.

Each function takes a :class:`GitContext`, runs the corresponding ``git``
command via :class:`GitRunner`, and shows the result in a modal dialog.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.git import GitCommandError, GitRunner
from rabbitsync.core.git_info import branches as list_branches, status as repo_status
from rabbitsync.core.git_resolve import GitContext
from rabbitsync.ui.theme import Spacing, Typography


def _runner(ctx: GitContext) -> GitRunner:
    if ctx.git_root is None:
        raise RuntimeError("git context has no working tree root")
    return GitRunner(ctx.git_root)


def _run_and_report(parent: QWidget, ctx: GitContext, args: list[str], *, title: str) -> None:
    """Run a git command, show stdout+stderr in a result dialog."""
    runner = _runner(ctx)
    try:
        result = runner.run(args, check=False, timeout=300)
    except Exception as exc:  # noqa: BLE001 -- show every failure to the user
        QMessageBox.critical(parent, title,
                             f"Could not run git: {exc}")
        return
    body = (result.stdout + ("\n" if result.stdout and result.stderr else "") + result.stderr).strip()
    if not body:
        body = f"(git exited with code {result.exit_code} and no output)"
    dialog = _OutputDialog(title=title, body=body, ok=result.ok, parent=parent)
    dialog.exec()


def fetch(parent: QWidget, ctx: GitContext) -> None:
    _run_and_report(parent, ctx, ["fetch", "--all", "--prune", "--progress"],
                    title="git fetch")


def pull(parent: QWidget, ctx: GitContext) -> None:
    """Default to fast-forward-only — refuse to merge without explicit consent."""
    _run_and_report(parent, ctx, ["pull", "--ff-only", "--progress"],
                    title="git pull")


def push(parent: QWidget, ctx: GitContext) -> None:
    """Push the current branch (with upstream-set if not configured)."""
    runner = _runner(ctx)
    s = repo_status(ctx)
    if s is None or s.branch is None:
        QMessageBox.warning(parent, "git push",
                            "No current branch to push (detached HEAD?).")
        return
    args: list[str] = ["push", "--progress"]
    if s.upstream is None:
        args += ["--set-upstream", "origin", s.branch]
    try:
        result = runner.run(args, check=False, timeout=300)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, "git push", f"Could not run git: {exc}")
        return
    body = (result.stdout + "\n" + result.stderr).strip() or "(no output)"
    _OutputDialog(title="git push", body=body, ok=result.ok, parent=parent).exec()


def quick_push(parent: QWidget, ctx: GitContext) -> None:
    """Stage all → auto-generate ``RabbitSync: …`` message → commit → push.

    Confirms the generated message with the user before committing.
    """
    from rabbitsync.core import commit_messages

    runner = _runner(ctx)

    # Stage everything in the registered subpath (or the whole repo).
    target = ctx.subpath if ctx.subpath else "."
    try:
        runner.run(["add", "-A", "--", target], check=True, timeout=60)
    except GitCommandError as exc:
        QMessageBox.critical(parent, "Quick Push", f"Stage failed: {exc}")
        return

    # Anything to commit?
    porcelain = runner.run(["status", "--porcelain=v2"], check=False, timeout=15)
    has_staged = any(
        line.startswith(("1 ", "2 ", "u "))
        and len(line) > 2 and line[2] != "."
        for line in porcelain.stdout.splitlines()
    )
    if not has_staged:
        # Nothing staged — try push anyway in case there are unpushed commits.
        push(parent, ctx)
        return

    # Build the message and let the user tweak.
    s = repo_status(ctx)
    message = commit_messages.for_quick_push(s)

    edited, ok = _ask_text_multiline(
        parent, "Quick Push — confirm message",
        "Auto-generated commit message (edit if needed):",
        message,
    )
    if not ok:
        return
    if not edited.strip():
        edited = message
    if not commit_messages.is_safe_for_argv(edited):
        QMessageBox.warning(parent, "Quick Push",
                            "Commit message contains unprintable characters.")
        return

    try:
        commit_result = runner.run(["commit", "-m", edited], check=False, timeout=60)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, "Quick Push", f"Commit failed: {exc}")
        return
    if not commit_result.ok:
        QMessageBox.critical(parent, "Quick Push",
                             commit_result.stderr or commit_result.stdout
                             or f"git commit exited {commit_result.exit_code}")
        return

    # Push.
    push_status = repo_status(ctx)
    branch = push_status.branch if push_status is not None else None
    args: list[str] = ["push", "--progress"]
    if push_status is not None and push_status.upstream is None and branch:
        args += ["--set-upstream", "origin", branch]
    push_result = runner.run(args, check=False, timeout=300)
    body = (commit_result.stdout + "\n" + commit_result.stderr
            + "\n\n--- push ---\n"
            + push_result.stdout + "\n" + push_result.stderr).strip()
    _OutputDialog(title="Quick Push",
                  body=body or "(no output)",
                  ok=push_result.ok,
                  parent=parent).exec()


def _ask_text_multiline(parent: QWidget, title: str, prompt: str, default: str) -> tuple[str, bool]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.resize(560, 240)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
    layout.setSpacing(Spacing.SM)
    layout.addWidget(QLabel(prompt, dlg))
    field = QPlainTextEdit(dlg)
    field.setPlainText(default)
    layout.addWidget(field, 1)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dlg,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    return field.toPlainText(), accepted


def stash_save(parent: QWidget, ctx: GitContext) -> None:
    text, ok = _ask_text(parent, "Stash message", "Optional stash description:")
    if not ok:
        return
    args = ["stash", "push"]
    if text.strip():
        args += ["-m", text.strip()]
    _run_and_report(parent, ctx, args, title="git stash")


def stage_changes(parent: QWidget, ctx: GitContext) -> None:
    """Open a small picker that stages selected unstaged changes."""
    s = repo_status(ctx)
    if s is None:
        QMessageBox.information(parent, "Stage", "No git context.")
        return
    unstaged = [
        c for c in s.changes
        if c.is_untracked or c.worktree_status in {"M", "D"} or c.index_status == " "
    ]
    if not unstaged:
        QMessageBox.information(parent, "Stage", "Nothing to stage — working tree is clean.")
        return
    dlg = _StageDialog(unstaged, parent=parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    paths = dlg.selected_paths()
    if not paths:
        return
    runner = _runner(ctx)
    try:
        runner.run(["add", "--", *paths], check=True, timeout=60)
    except GitCommandError as exc:
        QMessageBox.critical(parent, "Stage", str(exc))
        return
    QMessageBox.information(parent, "Stage", f"Staged {len(paths)} path(s).")


def commit_dialog(parent: QWidget, ctx: GitContext) -> None:
    """Show staged changes and prompt for a commit message."""
    runner = _runner(ctx)
    try:
        diff_result = runner.run(["diff", "--cached", "--stat"], check=False, timeout=30)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, "Commit", f"Could not read staged diff: {exc}")
        return
    staged_summary = diff_result.stdout.strip() or "(nothing staged)"
    dlg = _CommitDialog(staged_summary=staged_summary, parent=parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    message = dlg.message()
    if not message.strip():
        QMessageBox.warning(parent, "Commit", "Commit message is empty.")
        return
    try:
        result = runner.run(["commit", "-m", message], check=False, timeout=60)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, "Commit", f"Could not run git: {exc}")
        return
    body = (result.stdout + "\n" + result.stderr).strip() or "(no output)"
    _OutputDialog(title="git commit", body=body, ok=result.ok, parent=parent).exec()


def branch_dialog(parent: QWidget, ctx: GitContext) -> None:
    """Switch between local branches or create a new one."""
    bs = list_branches(ctx)
    if not bs:
        QMessageBox.information(parent, "Branch", "No local branches available.")
        return
    dlg = _BranchDialog(branches=[b.name for b in bs],
                        current=next((b.name for b in bs if b.is_current), None),
                        parent=parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    selection = dlg.selection()
    if selection is None:
        return
    runner = _runner(ctx)
    if selection.create:
        args = ["checkout", "-b", selection.name]
    else:
        args = ["checkout", selection.name]
    _run_and_report_with_runner(parent, runner, args, title=f"git {' '.join(args)}")


def _run_and_report_with_runner(
    parent: QWidget, runner: GitRunner, args: list[str], *, title: str,
) -> None:
    try:
        result = runner.run(args, check=False, timeout=120)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, title, f"Could not run git: {exc}")
        return
    body = (result.stdout + "\n" + result.stderr).strip() or "(no output)"
    _OutputDialog(title=title, body=body, ok=result.ok, parent=parent).exec()


def _ask_text(parent: QWidget, title: str, prompt: str) -> tuple[str, bool]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
    layout.setSpacing(Spacing.SM)
    layout.addWidget(QLabel(prompt, dlg))
    field = QLineEdit(dlg)
    layout.addWidget(field)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dlg,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    return field.text(), accepted


class _OutputDialog(QDialog):
    def __init__(self, *, title: str, body: str, ok: bool, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)
        head = QLabel("Success" if ok else "Failed", self)
        head.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; font-weight: 600;"
        )
        layout.addWidget(head)
        view = QPlainTextEdit(self)
        view.setReadOnly(True)
        view.setPlainText(body)
        view.setStyleSheet(
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt;"
        )
        layout.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        for btn in buttons.buttons():
            btn.clicked.connect(self.accept)
        layout.addWidget(buttons)


class _StageDialog(QDialog):
    def __init__(self, changes, *, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setWindowTitle("Stage changes")
        self.setModal(True)
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(QLabel("Pick files to stage:", self))
        self._list = QListWidget(self)
        for c in changes:
            it = QListWidgetItem(f"  {c.worktree_status or '?'}  {c.rel_path}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setData(Qt.ItemDataRole.UserRole, c.rel_path)
            self._list.addItem(it)
        layout.addWidget(self._list, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_paths(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                p = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(p, str):
                    out.append(p)
        return out


class _CommitDialog(QDialog):
    def __init__(self, *, staged_summary: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Commit")
        self.setModal(True)
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(QLabel("Staged changes:", self))
        view = QPlainTextEdit(self)
        view.setReadOnly(True)
        view.setPlainText(staged_summary)
        view.setStyleSheet(
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt;"
        )
        view.setMaximumHeight(220)
        layout.addWidget(view)
        layout.addWidget(QLabel("Commit message:", self))
        self._message = QPlainTextEdit(self)
        layout.addWidget(self._message, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def message(self) -> str:
        return self._message.toPlainText()


class _BranchDialog(QDialog):
    class _Sel:
        def __init__(self, name: str, create: bool) -> None:
            self.name = name
            self.create = create

    def __init__(
        self, *, branches: list[str], current: str | None, parent: QWidget | None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Branch")
        self.setModal(True)
        self.resize(440, 280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(QLabel("Switch to existing branch:", self))
        self._combo = QComboBox(self)
        self._combo.addItems(branches)
        if current is not None and current in branches:
            self._combo.setCurrentIndex(branches.index(current))
        layout.addWidget(self._combo)

        layout.addWidget(QLabel("…or create a new branch:", self))
        self._new = QLineEdit(self)
        self._new.setPlaceholderText("new branch name (e.g. feature/login)")
        layout.addWidget(self._new)

        layout.addStretch(1)
        buttons = QHBoxLayout()
        switch_btn = QPushButton("Switch", self)
        create_btn = QPushButton("Create && switch", self)
        cancel_btn = QPushButton("Cancel", self)
        switch_btn.clicked.connect(self._do_switch)
        create_btn.clicked.connect(self._do_create)
        cancel_btn.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(switch_btn)
        buttons.addWidget(create_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        self._sel: _BranchDialog._Sel | None = None

    def selection(self) -> _Sel | None:
        return self._sel

    def _do_switch(self) -> None:
        name = self._combo.currentText()
        if not name:
            return
        self._sel = self._Sel(name, create=False)
        self.accept()

    def _do_create(self) -> None:
        name = self._new.text().strip()
        if not name:
            QMessageBox.warning(self, "Branch", "Enter a name for the new branch.")
            return
        self._sel = self._Sel(name, create=True)
        self.accept()


__all__ = [
    "branch_dialog",
    "commit_dialog",
    "fetch",
    "pull",
    "push",
    "quick_push",
    "stage_changes",
    "stash_save",
]


# Reference Callable for forward-extension parity.
_ = Callable
