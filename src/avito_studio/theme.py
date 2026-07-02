"""Единый визуальный стиль студии: Fusion + светлая QSS-тема + цвета статусов.

Все цвета — здесь, чтобы таблица (ForegroundRole) и QSS не разъезжались. Кнопки-акценты
помечаются свойством accent="true" (см. QPushButton[accent="true"] ниже), подсказки в
диалогах — свойством hint="true"."""
from __future__ import annotations
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QStyleFactory

# Цвета значений в таблице (не в QSS: ForegroundRole задаётся моделью per-cell)
GREEN = QColor("#1a7f37")    # карточка есть / статус active
RED = QColor("#c62828")      # статус blocked/rejected/removed
MUTED = QColor("#8a919c")    # «—», нет данных, нулевой остаток

_QSS = """
QMainWindow, QDialog { background: #f4f6f9; }

QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e2e6ec;
    padding: 5px 8px;
    spacing: 4px;
}
QToolBar::separator { background: #e2e6ec; width: 1px; margin: 6px 6px; }
QToolButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    color: #2b3138;
}
QToolButton:hover { background: #edf1f6; }
QToolButton:pressed { background: #e1e7ef; }
QToolButton:disabled { color: #a6adb8; }

QLineEdit, QSpinBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #d3d9e2;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #cfe3ff;
    selection-color: #1b2430;
}
QSpinBox { padding: 4px 8px; }
QLineEdit:focus, QSpinBox:focus, QTextEdit:focus { border-color: #4a90d9; }

QTableView {
    background: #ffffff;
    alternate-background-color: #f7f9fc;
    border: 1px solid #e2e6ec;
    border-radius: 6px;
    gridline-color: transparent;
    selection-background-color: #e3efff;
    selection-color: #1b2430;
}
QTableView::item { padding: 2px 6px; }
QHeaderView::section {
    background: #fbfcfe;
    color: #5b6470;
    border: none;
    border-bottom: 2px solid #e2e6ec;
    padding: 7px 8px;
    font-weight: 600;
}

QPushButton {
    background: #ffffff;
    color: #2b3138;
    border: 1px solid #ccd3dd;
    border-radius: 6px;
    padding: 7px 18px;
    min-width: 72px;
}
QPushButton:hover { background: #f1f4f8; }
QPushButton:pressed { background: #e5eaf1; }
QPushButton:disabled { color: #a6adb8; background: #f1f2f4; border-color: #e0e3e8; }
QPushButton[accent="true"] {
    background: #0d9b53;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QPushButton[accent="true"]:hover { background: #0b8748; }
QPushButton[accent="true"]:pressed { background: #09743e; }
QPushButton[accent="true"]:disabled { background: #a9d9bf; color: #ffffff; }

QStatusBar { background: #ffffff; border-top: 1px solid #e2e6ec; color: #5b6470; }
QStatusBar[error="true"] { color: #c62828; font-weight: 600; }

QLabel[hint="true"] { color: #77808c; }
QMessageBox { background: #ffffff; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    app.setStyleSheet(_QSS)
