"""Comprehensive QSS stylesheet built from the active palette.

Applied once at QApplication level so every widget — buttons, combos, lists,
trees, tabs, scrollbars, menus, splitters, status bar — inherits a consistent
visual language. Per-widget setStyleSheet calls elsewhere in the app are
purely additive (they add object-name-scoped tweaks).
"""

from __future__ import annotations

from rabbitsync.ui.theme import Palette, Radius, Spacing, Typography


def build(palette: Palette) -> str:
    """Return a QSS string styling every widget the app uses."""
    p = palette
    r = Radius
    t = Typography
    _ = Spacing  # reserved for future use

    return f"""
/* ---------- Globals ---------- */
* {{
    font-family: "{t.UI_FAMILY}";
    font-size: {t.BASE_PT}pt;
    color: {p.fg};
}}

QWidget {{
    background-color: {p.bg};
    color: {p.fg};
    selection-background-color: {p.selection};
    selection-color: {p.fg};
}}

QToolTip {{
    background-color: {p.bg_elevated};
    color: {p.fg};
    border: 1px solid {p.border};
    padding: 4px 6px;
    border-radius: {r.SM}px;
}}

/* ---------- Header strip & shells ---------- */
#HeaderStrip {{
    background-color: {p.bg_subtle};
    border-bottom: 1px solid {p.border_subtle};
}}

#PairHeader {{
    background-color: {p.bg_subtle};
    border-bottom: 1px solid {p.border_subtle};
}}

#Sidebar {{
    background-color: {p.bg_subtle};
    border-right: 1px solid {p.border_subtle};
}}

#central {{
    background-color: {p.bg};
}}

QMainWindow {{
    background-color: {p.bg};
}}

/* ---------- Labels ---------- */
QLabel {{
    background: transparent;
    color: {p.fg};
}}

QLabel[role="muted"] {{
    color: {p.fg_muted};
}}

QLabel[role="title"] {{
    font-size: {t.HEADER_LG_PT}pt;
    font-weight: 600;
    color: {p.fg};
}}

QLabel[role="header"] {{
    font-size: {t.HEADER_PT}pt;
    font-weight: 600;
    color: {p.fg};
}}

/* ---------- Push buttons ---------- */
QPushButton {{
    background-color: {p.bg_elevated};
    color: {p.fg};
    border: 1px solid {p.border};
    border-radius: {r.MD}px;
    padding: 4px 10px;
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: {p.bg_hover};
    border-color: {p.border_strong};
}}

QPushButton:pressed {{
    background-color: {p.bg_active};
}}

QPushButton:disabled {{
    color: {p.fg_subtle};
    background-color: {p.bg_subtle};
    border-color: {p.border_subtle};
}}

QPushButton:default,
QPushButton[role="primary"] {{
    background-color: {p.accent};
    color: white;
    border: 1px solid {p.accent};
}}

QPushButton:default:hover,
QPushButton[role="primary"]:hover {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
}}

QPushButton:flat {{
    background-color: transparent;
    border: 1px solid transparent;
}}

QPushButton:flat:hover {{
    background-color: {p.bg_hover};
    border-color: transparent;
}}

QPushButton:flat:pressed {{
    background-color: {p.bg_active};
}}

/* ---------- Tool buttons ---------- */
QToolButton {{
    background-color: transparent;
    color: {p.fg};
    border: 1px solid transparent;
    border-radius: {r.MD}px;
    padding: 3px 8px;
}}

QToolButton:hover {{
    background-color: {p.bg_hover};
    border-color: {p.border_subtle};
}}

QToolButton:pressed {{
    background-color: {p.bg_active};
}}

QToolButton::menu-indicator {{
    image: none;  /* the tool buttons that need an indicator add their own ▾ */
}}

/* ---------- Line edits & plain text edits ---------- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {p.bg};
    color: {p.fg};
    border: 1px solid {p.border};
    border-radius: {r.MD}px;
    padding: 3px 6px;
    selection-background-color: {p.selection};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p.accent};
}}

QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    background-color: {p.bg_subtle};
    color: {p.fg_subtle};
}}

QLineEdit[echoMode="2"] {{
    /* password fields */
    font-family: "{t.MONO_FAMILY}";
}}

/* ---------- Combo box ---------- */
QComboBox {{
    background-color: {p.bg_elevated};
    color: {p.fg};
    border: 1px solid {p.border};
    border-radius: {r.MD}px;
    padding: 2px 6px;
    min-height: 18px;
}}

QComboBox:hover {{
    border-color: {p.border_strong};
}}

QComboBox:focus {{
    border-color: {p.accent};
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
    background: transparent;
}}

QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.fg_muted};
    margin-right: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.bg_elevated};
    color: {p.fg};
    border: 1px solid {p.border};
    selection-background-color: {p.bg_active};
    outline: none;
    padding: 2px;
}}

/* ---------- Spin box ---------- */
QSpinBox, QDoubleSpinBox {{
    background-color: {p.bg};
    color: {p.fg};
    border: 1px solid {p.border};
    border-radius: {r.MD}px;
    padding: 2px 6px;
    min-height: 18px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p.accent};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 16px;
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {p.fg_muted};
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {p.fg_muted};
}}

/* ---------- Check box ---------- */
QCheckBox {{
    background: transparent;
    color: {p.fg};
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {p.border_strong};
    border-radius: {r.SM}px;
    background-color: {p.bg};
}}

QCheckBox::indicator:hover {{
    border-color: {p.accent};
}}

QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border-color: {p.accent};
    image: none;
}}

QCheckBox::indicator:disabled {{
    background-color: {p.bg_subtle};
    border-color: {p.border_subtle};
}}

/* ---------- Tabs ---------- */
QTabWidget::pane {{
    border: none;
    background: {p.bg};
    top: -1px;
}}

QTabBar {{
    background: {p.bg_subtle};
    border-bottom: 1px solid {p.border_subtle};
}}

QTabBar::tab {{
    background: transparent;
    color: {p.fg_muted};
    padding: 6px 14px;
    border: none;
    border-bottom: 2px solid transparent;
    margin: 0;
    min-width: 60px;
}}

QTabBar::tab:hover {{
    color: {p.fg};
    background: {p.bg_hover};
}}

QTabBar::tab:selected {{
    color: {p.fg};
    background: {p.bg};
    border-bottom: 2px solid {p.accent};
}}

/* ---------- Trees, lists, tables ---------- */
QTreeView, QListView, QTableView, QListWidget, QTreeWidget, QTableWidget {{
    background-color: {p.bg};
    color: {p.fg};
    alternate-background-color: {p.bg_subtle};
    border: 1px solid {p.border_subtle};
    border-radius: {r.MD}px;
    selection-background-color: {p.bg_active};
    selection-color: {p.fg};
    outline: none;
    gridline-color: {p.border_subtle};
}}

QTreeView::item, QListView::item, QListWidget::item, QTreeWidget::item, QTableView::item {{
    padding: 3px 4px;
    border: none;
}}

QTreeView::item:hover, QListView::item:hover, QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {p.bg_hover};
}}

QTreeView::item:selected, QListView::item:selected,
QListWidget::item:selected, QTreeWidget::item:selected,
QTableView::item:selected {{
    background-color: {p.bg_active};
    color: {p.fg};
}}

QTreeView::branch:has-siblings:!adjoins-item,
QTreeView::branch:has-siblings:adjoins-item,
QTreeView::branch:!has-children:!has-siblings:adjoins-item {{
    border-image: none;
    image: none;
}}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    border-image: none;
    image: none;
}}

QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{
    border-image: none;
    image: none;
}}

/* ---------- Header view (table/tree column headers) ---------- */
QHeaderView::section {{
    background-color: {p.bg_subtle};
    color: {p.fg_muted};
    padding: 4px 8px;
    border: none;
    border-right: 1px solid {p.border_subtle};
    border-bottom: 1px solid {p.border_subtle};
    font-weight: 600;
}}

QHeaderView::section:hover {{
    background-color: {p.bg_hover};
}}

QHeaderView {{
    background-color: {p.bg_subtle};
}}

/* ---------- Scrollbars (slim, modern) ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {p.border_strong};
    min-height: 24px;
    border-radius: 5px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background: {p.fg_subtle};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    min-width: 24px;
    border-radius: 5px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {p.fg_subtle};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: transparent;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ---------- Menus ---------- */
QMenuBar {{
    background-color: {p.bg_subtle};
    color: {p.fg};
    border-bottom: 1px solid {p.border_subtle};
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
}}

QMenuBar::item:selected {{
    background-color: {p.bg_hover};
}}

QMenu {{
    background-color: {p.bg_elevated};
    color: {p.fg};
    border: 1px solid {p.border};
    border-radius: {r.MD}px;
    padding: 4px;
}}

QMenu::item {{
    background: transparent;
    padding: 5px 24px 5px 12px;
    border-radius: {r.SM}px;
}}

QMenu::item:selected {{
    background-color: {p.bg_active};
}}

QMenu::item:disabled {{
    color: {p.fg_subtle};
}}

QMenu::separator {{
    height: 1px;
    background: {p.border_subtle};
    margin: 4px 6px;
}}

QMenu::icon {{
    padding-left: 8px;
}}

/* ---------- Status bar ---------- */
QStatusBar {{
    background-color: {p.bg_subtle};
    color: {p.fg_muted};
    border-top: 1px solid {p.border_subtle};
}}

QStatusBar::item {{
    border: none;
}}

QStatusBar QLabel {{
    color: {p.fg_muted};
}}

/* ---------- Splitter ---------- */
QSplitter::handle {{
    background-color: {p.border_subtle};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

QSplitter::handle:hover {{
    background-color: {p.accent};
}}

/* ---------- Dock widgets ---------- */
QDockWidget {{
    color: {p.fg};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}

QDockWidget::title {{
    background-color: {p.bg_subtle};
    color: {p.fg_muted};
    padding: 4px 8px;
    border: none;
    border-bottom: 1px solid {p.border_subtle};
    text-align: left;
}}

/* ---------- Group boxes & frames ---------- */
QGroupBox {{
    border: 1px solid {p.border_subtle};
    border-radius: {r.MD}px;
    margin-top: 12px;
    padding: 8px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {p.fg_muted};
}}

QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    /* HLine / VLine */
    color: {p.border_subtle};
}}

/* ---------- Dialog buttons ---------- */
QDialog {{
    background-color: {p.bg};
}}

QDialogButtonBox QPushButton {{
    min-width: 72px;
}}

/* ---------- Progress bar ---------- */
QProgressBar {{
    background-color: {p.bg_subtle};
    border: 1px solid {p.border_subtle};
    border-radius: {r.MD}px;
    text-align: center;
    color: {p.fg};
    height: 18px;
}}

QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: {r.SM}px;
}}

/* ---------- Message box ---------- */
QMessageBox {{
    background-color: {p.bg_elevated};
}}

QMessageBox QLabel {{
    color: {p.fg};
}}
"""


__all__ = ["build"]
