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
QMainWindow, QDialog { background: #edf6fb; color: #14263f; }
QWidget#appShell { background: #edf6fb; }
QWidget#workspace { background: #edf6fb; }
QWidget#contentPage {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #eaf3ff, stop:1 #e7f8f8);
}

QFrame#sidebar {
    background: #f8fbff;
    border-right: 1px solid #d7e3ee;
}
QLabel#brandBadge {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #3189ee, stop:1 #20b8c5);
    color: white;
    border-radius: 13px;
    font-size: 15px;
    font-weight: 700;
}
QLabel#brandTitle { color: #14263f; font-size: 15px; font-weight: 700; }
QLabel#brandSubtitle { color: #71839a; font-size: 10px; }
QLabel#navSection, QLabel#profileLabel {
    color: #8ba0b4;
    font-size: 9px;
    font-weight: 700;
}
QPushButton#navButton {
    min-width: 0;
    border: none;
    border-radius: 10px;
    padding: 10px 12px;
    text-align: left;
    color: #34455c;
    font-weight: 600;
    background: transparent;
}
QPushButton#navButton:hover { background: #e8f3fb; }
QPushButton#navButton:checked {
    color: white;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #3288eb, stop:1 #22b9c5);
}
QFrame#sidebarHint, QFrame#safetyCard {
    background: #ffffff;
    border: 1px solid #dce7f0;
    border-radius: 11px;
}
QLabel#hintTitle, QLabel#safetyTitle { color: #243b55; font-weight: 650; }
QLabel#hintText, QLabel#safetyText { color: #73859a; font-size: 10px; }
QLabel#safetyTitle { color: #1b9069; }

QFrame#topHeader {
    background: rgba(250, 253, 255, 245);
    border-bottom: 1px solid #d5e3ed;
}
QLabel#pageTitle { color: #14263f; font-size: 22px; font-weight: 700; }
QLabel#pageSubtitle { color: #6d8198; font-size: 11px; }
QComboBox {
    background: #ffffff;
    border: 1px solid #cedce8;
    border-radius: 9px;
    padding: 7px 11px;
    color: #243b55;
}
QComboBox:focus { border-color: #2d9fe5; }
QComboBox::drop-down { border: none; width: 28px; }

QFrame#statCard, QFrame#actionCard, QFrame#panelCard,
QFrame#filterCard, QFrame#tableCard {
    background: rgba(255, 255, 255, 248);
    border: 1px solid #d5e2eb;
    border-radius: 13px;
}
QLabel#statTitle { color: #657b94; font-size: 11px; font-weight: 600; }
QLabel#statValue { color: #13263f; font-size: 25px; font-weight: 750; }
QLabel#statCaption { color: #91a2b4; font-size: 10px; }
QLabel#sectionTitle, QLabel#panelTitle { color: #162b45; font-size: 14px; font-weight: 700; }
QLabel#panelSubtitle, QLabel#actionSubtitle { color: #6f839a; font-size: 11px; }
QLabel#actionTitle { color: #162b45; font-size: 13px; font-weight: 700; }
QFrame#tableHeading { background: transparent; border-bottom: 1px solid #d9e5ed; }

QToolBar {
    background: #ffffff;
    border: 1px solid #d5e2eb;
    border-radius: 13px;
    padding: 7px 9px;
    spacing: 3px;
}
QToolBar::separator { background: #e2e6ec; width: 1px; margin: 6px 6px; }
QToolButton {
    background: #f4f8fb;
    border: 1px solid #dfE8ef;
    border-radius: 8px;
    padding: 7px 11px;
    color: #2c4159;
    font-weight: 600;
}
QToolButton:hover { background: #e9f4fb; border-color: #bcdced; }
QToolButton:pressed { background: #dceef8; }
QToolButton:disabled { color: #a6adb8; }
QToolButton#cardActionButton {
    text-align: left;
    background: #f5f9fc;
    border-color: #dce8ef;
}

QLineEdit, QSpinBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #cedce8;
    border-radius: 9px;
    padding: 7px 11px;
    selection-background-color: #cfe3ff;
    selection-color: #1b2430;
}
QSpinBox { padding: 4px 8px; }
QLineEdit:focus, QSpinBox:focus, QTextEdit:focus { border-color: #2d9fe5; }

QTableView {
    background: #ffffff;
    alternate-background-color: #f6fbfd;
    border: none;
    border-bottom-left-radius: 13px;
    border-bottom-right-radius: 13px;
    gridline-color: transparent;
    selection-background-color: #dff2fb;
    selection-color: #1b2430;
}
QTableView::item { padding: 3px 7px; border-bottom: 1px solid #edf2f5; }
QHeaderView::section {
    background: #f7fafc;
    color: #60758d;
    border: none;
    border-bottom: 1px solid #dce6ed;
    padding: 8px;
    font-weight: 600;
}

QPushButton {
    background: #ffffff;
    color: #2c4159;
    border: 1px solid #cedce8;
    border-radius: 9px;
    padding: 8px 16px;
    min-width: 72px;
}
QPushButton:hover { background: #edf6fb; }
QPushButton:pressed { background: #dfeef6; }
QPushButton:disabled { color: #a6adb8; background: #f1f2f4; border-color: #e0e3e8; }
QPushButton#primaryButton {
    color: #ffffff;
    border: none;
    font-weight: 700;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #3288eb, stop:1 #22b9c5);
}
QPushButton#primaryButton:hover { background: #258fd1; }
QPushButton[accent="true"] {
    background: #1b9d71;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QPushButton[accent="true"]:hover { background: #178861; }
QPushButton[accent="true"]:pressed { background: #137451; }
QPushButton[accent="true"]:disabled { background: #a9d9bf; color: #ffffff; }

QStatusBar { background: #ffffff; border-top: 1px solid #d7e3eb; color: #60758d; }
QStatusBar[error="true"] { color: #c62828; font-weight: 600; }

QLabel[hint="true"] { color: #77808c; }
QMessageBox { background: #ffffff; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    app.setStyleSheet(_QSS)
