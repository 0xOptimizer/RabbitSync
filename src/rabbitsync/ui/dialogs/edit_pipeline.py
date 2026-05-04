"""Pipeline editor — argv-only steps with constrained cwd dropdown.

There is NO free-text command field anywhere; each argv argument is a
separate input field. This is the structural defense that prevents the
user from typing a shell command into RabbitSync.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter
from rabbitsync.ui.theme import Spacing, Typography


@dataclass
class StepRow:
    name: str = ""
    argv: list[str] = field(default_factory=list)
    cwd_kind: str = "source"           # 'source' | 'copy'
    cwd_subpath: str = ""
    timeout_s: int = 300
    on_fail: str = "abort"             # 'abort' | 'continue'
    inputs_globs: list[str] = field(default_factory=list)
    env_extra: dict[str, str] = field(default_factory=dict)


class EditPipelineDialog(QDialog):
    def __init__(
        self,
        *,
        pair_id: str,
        writer: DbWriter,
        pipeline_id: int | None = None,
        factory: ConnectionFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit pipeline")
        self.setModal(True)
        self.resize(900, 620)
        self._pair_id = pair_id
        self._writer = writer
        self._factory = factory or ConnectionFactory()
        self._pipeline_id = pipeline_id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        outer.setSpacing(Spacing.MD)

        # Pipeline header
        header_form = QFormLayout()
        self._name_input = QLineEdit(self)
        self._name_input.setPlaceholderText("e.g. test-and-deploy")
        header_form.addRow("Pipeline name", self._name_input)
        outer.addLayout(header_form)

        # Steps list + per-step editor
        body = QSplitter(Qt.Orientation.Horizontal, self)

        left = QFrame(body)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(Spacing.SM)
        ll.addWidget(QLabel("Steps", left))
        self._steps_list = QListWidget(left)
        self._steps_list.currentRowChanged.connect(self._on_step_selected)
        ll.addWidget(self._steps_list, 1)
        sb = QHBoxLayout()
        add_btn = QPushButton("+", left)
        add_btn.setToolTip("Add a step")
        add_btn.clicked.connect(self._add_step)
        del_btn = QPushButton("−", left)
        del_btn.setToolTip("Remove the selected step")
        del_btn.clicked.connect(self._remove_step)
        up_btn = QPushButton("↑", left)
        up_btn.clicked.connect(lambda: self._move_step(-1))
        down_btn = QPushButton("↓", left)
        down_btn.clicked.connect(lambda: self._move_step(+1))
        for b in (add_btn, del_btn, up_btn, down_btn):
            b.setFlat(False)
            sb.addWidget(b)
        sb.addStretch(1)
        ll.addLayout(sb)
        body.addWidget(left)

        right = QFrame(body)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(Spacing.SM)
        self._editor = _StepEditor(right)
        self._editor.setEnabled(False)
        rl.addWidget(self._editor, 1)
        body.addWidget(right)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 2)
        outer.addWidget(body, 1)

        # Footer buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._steps: list[StepRow] = []
        if self._pipeline_id is not None:
            self._load_existing(self._pipeline_id)

    # -- Loading existing -------------------------------------------------

    def _load_existing(self, pipeline_id: int) -> None:
        with closing(self._factory.reader()) as conn:
            row = conn.execute(
                "SELECT name FROM pipelines WHERE id = ?;", (pipeline_id,),
            ).fetchone()
            if row is not None:
                self._name_input.setText(row["name"])
            for sr in conn.execute(
                "SELECT * FROM pipeline_steps WHERE pipeline_id = ? ORDER BY ordinal;",
                (pipeline_id,),
            ):
                self._steps.append(StepRow(
                    name=sr["name"],
                    argv=_safe_list(sr["argv_json"]),
                    cwd_kind=sr["cwd_kind"],
                    cwd_subpath=sr["cwd_subpath"] or "",
                    timeout_s=int(sr["timeout_s"]),
                    on_fail=sr["on_fail"],
                    inputs_globs=_safe_list(sr["inputs_globs_json"]),
                    env_extra=_safe_dict(sr["env_extra_json"]),
                ))
        self._refresh_steps_list()
        if self._steps:
            self._steps_list.setCurrentRow(0)

    # -- Step list operations --------------------------------------------

    def _refresh_steps_list(self) -> None:
        self._steps_list.clear()
        for sr in self._steps:
            label = sr.name or "(unnamed step)"
            self._steps_list.addItem(QListWidgetItem(label))

    def _add_step(self) -> None:
        self._save_current_into_model()
        self._steps.append(StepRow(name=f"step-{len(self._steps) + 1}"))
        self._refresh_steps_list()
        self._steps_list.setCurrentRow(len(self._steps) - 1)

    def _remove_step(self) -> None:
        idx = self._steps_list.currentRow()
        if idx < 0 or idx >= len(self._steps):
            return
        del self._steps[idx]
        self._refresh_steps_list()
        if self._steps:
            self._steps_list.setCurrentRow(min(idx, len(self._steps) - 1))
        else:
            self._editor.set_step(None)

    def _move_step(self, delta: int) -> None:
        idx = self._steps_list.currentRow()
        new_idx = idx + delta
        if idx < 0 or new_idx < 0 or new_idx >= len(self._steps):
            return
        self._save_current_into_model()
        self._steps[idx], self._steps[new_idx] = self._steps[new_idx], self._steps[idx]
        self._refresh_steps_list()
        self._steps_list.setCurrentRow(new_idx)

    def _on_step_selected(self, idx: int) -> None:
        self._save_current_into_model()
        if idx < 0 or idx >= len(self._steps):
            self._editor.set_step(None)
            return
        self._editor.set_step(self._steps[idx])
        self._editor_index = idx

    def _save_current_into_model(self) -> None:
        idx = getattr(self, "_editor_index", -1)
        if 0 <= idx < len(self._steps):
            updated = self._editor.snapshot()
            if updated is not None:
                self._steps[idx] = updated
                lbl = self._steps_list.item(idx)
                if lbl is not None:
                    lbl.setText(updated.name or "(unnamed step)")

    # -- Save -------------------------------------------------------------

    def _on_accept(self) -> None:
        self._save_current_into_model()
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Pipeline", "Pipeline name is required.")
            return
        if not self._steps:
            QMessageBox.warning(self, "Pipeline", "Add at least one step.")
            return
        for i, sr in enumerate(self._steps):
            if not sr.name.strip():
                QMessageBox.warning(self, "Pipeline", f"Step {i + 1} is missing a name.")
                return
            if not sr.argv or not sr.argv[0].strip():
                QMessageBox.warning(self, "Pipeline",
                                    f"Step '{sr.name}' has no argv (must include at least the binary).")
                return

        self._save_to_db(name)
        self.accept()

    def _save_to_db(self, name: str) -> None:
        pair_id = self._pair_id
        steps = self._steps
        existing_id = self._pipeline_id

        def _do(conn: sqlite3.Connection) -> None:
            now = _now()
            if existing_id is None:
                # Create.
                conn.execute(
                    "INSERT INTO pipelines (pair_id, name, ordinal, created_at, updated_at) "
                    "VALUES (?, ?, COALESCE((SELECT MAX(ordinal)+1 FROM pipelines WHERE pair_id=?), 0), ?, ?);",
                    (pair_id, name, pair_id, now, now),
                )
                pid = int(conn.execute(
                    "SELECT id FROM pipelines WHERE pair_id=? AND name=?;",
                    (pair_id, name),
                ).fetchone()[0])
            else:
                conn.execute(
                    "UPDATE pipelines SET name=?, updated_at=? WHERE id=?;",
                    (name, now, existing_id),
                )
                conn.execute(
                    "DELETE FROM pipeline_steps WHERE pipeline_id=?;",
                    (existing_id,),
                )
                pid = existing_id
            for ord_idx, sr in enumerate(steps):
                conn.execute(
                    "INSERT INTO pipeline_steps "
                    "(pipeline_id, ordinal, name, argv_json, cwd_kind, cwd_subpath, "
                    " env_extra_json, timeout_s, on_fail, inputs_globs_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        pid, ord_idx, sr.name,
                        json.dumps(sr.argv), sr.cwd_kind, sr.cwd_subpath or None,
                        json.dumps(sr.env_extra), int(sr.timeout_s), sr.on_fail,
                        json.dumps(sr.inputs_globs),
                    ),
                )

        self._writer.execute(_do)


class _StepEditor(QFrame):
    """One step's editor — argv builder + cwd dropdown + safety constraints."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self._step: StepRow | None = None

        layout = QFormLayout(self)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.SM)

        self._name = QLineEdit(self)
        layout.addRow("Step name", self._name)

        # Argv builder — list of QLineEdits with add/remove, NO free-text command box
        self._argv_widget = QFrame(self)
        self._argv_layout = QVBoxLayout(self._argv_widget)
        self._argv_layout.setContentsMargins(0, 0, 0, 0)
        self._argv_layout.setSpacing(2)
        self._argv_inputs: list[QLineEdit] = []
        argv_section = QFrame(self)
        avs = QVBoxLayout(argv_section)
        avs.setContentsMargins(0, 0, 0, 0)
        avs.setSpacing(Spacing.XS)
        avs.addWidget(self._argv_widget)
        argv_buttons = QHBoxLayout()
        add_btn = QPushButton("+ argument", self)
        add_btn.clicked.connect(lambda: self._append_argv_input(""))
        argv_buttons.addWidget(add_btn)
        argv_buttons.addStretch(1)
        avs.addLayout(argv_buttons)
        layout.addRow(QLabel("Command (argv — first is the binary)", self), argv_section)

        self._cwd_kind = QComboBox(self)
        self._cwd_kind.addItem("Pair's source folder", "source")
        self._cwd_kind.addItem("Pair's copy folder", "copy")
        layout.addRow("Working directory", self._cwd_kind)

        self._cwd_subpath = QLineEdit(self)
        self._cwd_subpath.setPlaceholderText("optional subpath relative to the chosen folder")
        layout.addRow("Subpath", self._cwd_subpath)

        self._timeout = QSpinBox(self)
        self._timeout.setRange(5, 3600)
        self._timeout.setValue(300)
        layout.addRow("Timeout (s)", self._timeout)

        self._on_fail = QComboBox(self)
        self._on_fail.addItems(["abort", "continue"])
        layout.addRow("On failure", self._on_fail)

        self._inputs = QLineEdit(self)
        self._inputs.setPlaceholderText("comma-separated globs, e.g. src/**, tests/**")
        layout.addRow("Cache inputs", self._inputs)

        self._env_extra = QLineEdit(self)
        self._env_extra.setPlaceholderText("KEY1=value, KEY2=value (extra env vars)")
        layout.addRow("Extra env", self._env_extra)

        # Safety footer
        warn = QLabel(
            "RabbitSync runs steps with shell=False. Use a script "
            "(.ps1/.bat/.sh) checked into your repo if you need pipes or chaining.",
            self,
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: gray;"
        )
        layout.addRow(warn)

    def set_step(self, sr: StepRow | None) -> None:
        self._step = sr
        self.setEnabled(sr is not None)
        if sr is None:
            return
        self._name.setText(sr.name)
        self._cwd_kind.setCurrentIndex(0 if sr.cwd_kind != "copy" else 1)
        self._cwd_subpath.setText(sr.cwd_subpath)
        self._timeout.setValue(int(sr.timeout_s))
        self._on_fail.setCurrentText(sr.on_fail)
        self._inputs.setText(", ".join(sr.inputs_globs))
        self._env_extra.setText(", ".join(f"{k}={v}" for k, v in sr.env_extra.items()))

        # Rebuild argv inputs.
        for w in self._argv_inputs:
            w.deleteLater()
        self._argv_inputs.clear()
        for arg in sr.argv:
            self._append_argv_input(arg)
        if not sr.argv:
            self._append_argv_input("")

    def snapshot(self) -> StepRow | None:
        if self._step is None:
            return None
        argv = [w.text() for w in self._argv_inputs if w.text().strip()]
        env_extra: dict[str, str] = {}
        for token in self._env_extra.text().split(","):
            token = token.strip()
            if "=" in token:
                k, v = token.split("=", 1)
                env_extra[k.strip()] = v.strip()
        inputs_globs = [g.strip() for g in self._inputs.text().split(",") if g.strip()]
        return StepRow(
            name=self._name.text().strip(),
            argv=argv,
            cwd_kind=self._cwd_kind.currentData(),
            cwd_subpath=self._cwd_subpath.text().strip(),
            timeout_s=int(self._timeout.value()),
            on_fail=self._on_fail.currentText(),
            inputs_globs=inputs_globs,
            env_extra=env_extra,
        )

    def _append_argv_input(self, value: str) -> None:
        line = QLineEdit(self)
        line.setPlaceholderText("argument")
        line.setText(value)
        if not self._argv_inputs:
            line.setPlaceholderText("binary (e.g. python)")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line, 1)
        rm = QPushButton("−", self)
        rm.setFixedWidth(28)
        rm.clicked.connect(lambda: self._remove_argv_input(line))
        row.addWidget(rm)
        wrapper = QWidget(self)
        wrapper.setLayout(row)
        self._argv_layout.addWidget(wrapper)
        line._wrapper = wrapper  # type: ignore[attr-defined]
        self._argv_inputs.append(line)

    def _remove_argv_input(self, line: QLineEdit) -> None:
        if line not in self._argv_inputs:
            return
        self._argv_inputs.remove(line)
        wrapper = getattr(line, "_wrapper", None)
        if wrapper is not None:
            wrapper.deleteLater()
        else:
            line.deleteLater()


def _safe_list(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        v = json.loads(text)
        return [str(x) for x in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _safe_dict(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    try:
        v = json.loads(text)
        return {str(k): str(val) for k, val in v.items()} if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


__all__ = ["EditPipelineDialog", "StepRow"]


_ = Any
QTabWidget  # type: ignore[name-defined]  # imported for completeness
