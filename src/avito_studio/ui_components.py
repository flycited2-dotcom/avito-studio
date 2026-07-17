"""Small reusable building blocks for the Avito Studio visual language.

The widgets in this module intentionally contain no application logic. They only
apply semantic object names/properties consumed by avito_studio.theme, so dialogs
can share the main window's cards and button hierarchy without local style sheets.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


BUTTON_ROLES = frozenset({"primary", "secondary", "danger", "ghost", "success"})


def _repolish(widget: QWidget) -> None:
    """Refresh QSS after changing a dynamic property on an existing widget."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_button_role(button: QPushButton, role: str) -> QPushButton:
    """Assign a semantic visual role and return button for compact builders."""
    if role not in BUTTON_ROLES:
        raise ValueError(f"Unknown button role: {role}")
    button.setProperty("role", role)
    button.setCursor(Qt.PointingHandCursor)
    _repolish(button)
    return button


def role_button(
    text: str,
    role: str = "secondary",
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a push button styled by semantic role rather than local QSS."""
    return set_button_role(QPushButton(text, parent), role)


class Card(QFrame):
    """Standard white card used by pages and dialogs."""

    def __init__(self, parent: QWidget | None = None, *, object_name: str = "dialogCard"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)


class FormSection(Card):
    """Card with an optional heading and a public layout for form content."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent, object_name="formSection")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(10)
        if title:
            title_label = QLabel(title, objectName="sectionTitle")
            self.layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle, objectName="sectionSubtitle")
            subtitle_label.setWordWrap(True)
            self.layout.addWidget(subtitle_label)
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(10)
        self.layout.addLayout(self.content_layout)


def dialog_header(
    title: str,
    subtitle: str = "",
    *,
    badge: str = "AS",
    parent: QWidget | None = None,
) -> QFrame:
    """Build the shared dialog header used above a scrollable form body."""
    header = QFrame(parent, objectName="dialogHeader")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(22, 18, 22, 16)
    layout.setSpacing(13)
    if badge:
        badge_label = QLabel(badge, objectName="dialogBadge")
        badge_label.setAlignment(Qt.AlignCenter)
        badge_label.setFixedSize(42, 42)
        layout.addWidget(badge_label)
    titles = QVBoxLayout()
    titles.setSpacing(2)
    titles.addWidget(QLabel(title, objectName="dialogTitle"))
    if subtitle:
        subtitle_label = QLabel(subtitle, objectName="dialogSubtitle")
        subtitle_label.setWordWrap(True)
        titles.addWidget(subtitle_label)
    layout.addLayout(titles, 1)
    return header


def dialog_footer(
    buttons: Iterable[QPushButton],
    *,
    parent: QWidget | None = None,
) -> QFrame:
    """Build a right-aligned, visually separated dialog action footer."""
    footer = QFrame(parent, objectName="dialogFooter")
    layout = QHBoxLayout(footer)
    layout.setContentsMargins(22, 13, 22, 15)
    layout.setSpacing(9)
    layout.addStretch(1)
    for button in buttons:
        layout.addWidget(button)
    return footer


def get_open_file_name(
    parent: QWidget | None = None,
    caption: str = "Выбрать файл",
    directory: str = "",
    file_filter: str = "Все файлы (*)",
) -> tuple[str, str]:
    """Themed non-native equivalent of QFileDialog.getOpenFileName."""
    dialog = QFileDialog(parent, caption, directory, file_filter)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    dialog.setFileMode(QFileDialog.ExistingFile)
    dialog.setAcceptMode(QFileDialog.AcceptOpen)
    dialog.setObjectName("themedFileDialog")
    if dialog.exec() != QDialog.Accepted:
        return "", ""
    selected = dialog.selectedFiles()
    return (selected[0] if selected else "", dialog.selectedNameFilter())
