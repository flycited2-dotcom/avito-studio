"""Форма ручного добавления товара в выгрузку Avito: артикул поставщика (должен существовать как
продукт в БД oasis, просто без остатка на складе) + цена + опционально имя серии + фото/УТП.
Фото и УТП привязаны к артикулу и грузятся сразу — публикация для них не нужна. Описание для
объявления Avito привязано к КЛЮЧУ СЕРИИ (источник+бренд+серия), а источник/бренд узнаются только
из реальной записи в БД поставщика — до первой публикации студия их не знает, поэтому описание
задаётся отдельно, двойным кликом по строке после того, как товар появится в таблице.
«Опубликовать» в главном окне уже разберётся с деплоем force_include/manual_photos/manual_card_brief."""
from __future__ import annotations
from pathlib import Path
import re
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton,
                               QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QTextEdit,
                               QFileDialog)
from avito_studio.local_config import LocalConfig
from avito_studio.photo_upload import is_safe_nc_code


_MODEL_TOKEN = re.compile(r"\b[A-ZА-ЯЁ]{2,8}-[A-ZА-ЯЁ0-9./-]{3,}\b", re.IGNORECASE)
_INTERNAL_NC = re.compile(r"^НС-\d+$", re.IGNORECASE)


def model_hint(text: str) -> str | None:
    """Достаёт модель из вставленного названия только для понятной подсказки пользователю."""
    match = _MODEL_TOKEN.search(text or "")
    return match.group(0) if match else None


def is_internal_nc_code(value: str) -> bool:
    """force_include для Oasis работает только с внутренним кодом каталога НС-<цифры>."""
    return bool(value and _INTERNAL_NC.fullmatch(value.strip()) and is_safe_nc_code(value))


class AddForcedProductDialog(QDialog):
    def __init__(self, local_cfg: LocalConfig, ssh, parent=None):
        super().__init__(parent)
        self.local_cfg = local_cfg
        self.ssh = ssh
        self._new_photo_path: Path | None = None
        self.setWindowTitle("Добавить товар вручную")
        self.resize(520, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        hint = QLabel(
            "Нужен внутренний код поставщика вида НС-1480532 — не модель и не полное название.\n"
            "По этому коду сервер находит точный товар, даже если его сейчас нет на складе.")
        hint.setWordWrap(True)
        hint.setProperty("hint", True)
        layout.addWidget(hint)

        form = QFormLayout()

        self.nc_field = QLineEdit()
        self.nc_field.setPlaceholderText("например: НС-1480532")
        self.nc_field.textChanged.connect(self._update_save_enabled)
        nc_box = QVBoxLayout()
        nc_box.setContentsMargins(0, 0, 0, 0)
        nc_box.setSpacing(3)
        nc_box.addWidget(self.nc_field)
        self.nc_error = QLabel("")
        self.nc_error.setWordWrap(True)
        self.nc_error.setProperty("fieldError", True)
        nc_box.addWidget(self.nc_error)
        form.addRow("Внутренний код товара:", nc_box)

        self.price_field = QSpinBox()
        self.price_field.setRange(0, 10_000_000)
        self.price_field.setSuffix(" ₽")
        form.addRow("Цена:", self.price_field)

        self.series_field = QLineEdit()
        self.series_field.setPlaceholderText("необязательно — своё объявление, а не общая серия")
        form.addRow("Имя серии:", self.series_field)

        photo_row = QHBoxLayout()
        self.photo_label = QLabel("(нет фото)")
        photo_btn = QPushButton("Выбрать файл…")
        photo_btn.clicked.connect(self._choose_photo)
        photo_row.addWidget(self.photo_label)
        photo_row.addWidget(photo_btn)
        form.addRow("Фото (необязательно):", photo_row)

        layout.addLayout(form)

        layout.addWidget(QLabel("УТП/характеристики для карточки (необязательно):"))
        self.utp_edit = QTextEdit()
        self.utp_edit.setPlaceholderText(
            "Оставьте пустым — фотоагент возьмёт стандартный текст после публикации.")
        self.utp_edit.setMaximumHeight(80)
        layout.addWidget(self.utp_edit)

        note = QLabel(
            "Описание для объявления Avito зависит от бренда/поставщика этого артикула — студия узнает "
            "их только после публикации. Задайте описание двойным кликом по строке в таблице, когда "
            "товар там появится (после «Обновить» → «Опубликовать»)."
        )
        note.setWordWrap(True)
        note.setProperty("hint", True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.save_btn = QPushButton("Добавить")
        self.save_btn.setProperty("accent", True)
        self.save_btn.setDefault(True)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._validate_and_accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

    def _update_save_enabled(self, text: str) -> None:
        nc_code = text.strip()
        valid = is_internal_nc_code(nc_code)
        self.save_btn.setEnabled(valid)
        if nc_code and not valid:
            model = model_hint(nc_code)
            detail = (f" Распознана модель {model}, но нужен соответствующий код НС-…."
                      if model else "")
            self.nc_error.setText(
                "Введите только внутренний код без пробелов и описания." + detail)
        else:
            self.nc_error.clear()

    def _choose_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать фото", "", "Изображения (*.jpg *.jpeg *.png)")
        if path:
            self._new_photo_path = Path(path)
            self.photo_label.setText(path)

    def _validate_and_accept(self) -> None:
        nc_code = self.nc_field.text().strip()
        if not is_internal_nc_code(nc_code):
            model = model_hint(nc_code)
            suffix = (f"\n\nВ названии распознана модель {model}. Найдите для неё "
                      "внутренний код НС-… и вставьте только его."
                      if model else "")
            QMessageBox.warning(
                self, "Нужен внутренний код товара",
                "Нельзя использовать полное название как артикул." + suffix)
            return
        if self.price_field.value() == 0:
            reply = QMessageBox.question(
                self, "Цена не указана",
                "Цена равна 0 ₽. Всё равно добавить товар с нулевой ценой?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.accept()

    def save(self) -> None:
        """Вызывается ПОСЛЕ exec()==Accepted (см. main_window._open_add_forced_dialog)."""
        nc = self.nc_field.text().strip()
        if not is_internal_nc_code(nc):
            raise ValueError(
                "Внутренний код товара должен быть указан без пробелов и полного названия")

        # Сначала выполняем единственную внешнюю операцию. Раньше force_include менялся ДО
        # загрузки фото: при ошибке в памяти LocalConfig оставалась полузаписанная карточка.
        photo_url = None
        if self._new_photo_path:
            from avito_studio.workers import upload_photo_blocking
            photo_url = upload_photo_blocking(
                self.ssh, self._new_photo_path, nc, parent=self)

        self.local_cfg.add_force_include(nc, self.price_field.value(),
                                         series=self.series_field.text().strip() or None)
        if photo_url:
            self.local_cfg.set_manual_photo(nc, photo_url)
        if self.utp_edit.toPlainText().strip():
            self.local_cfg.set_card_brief(nc, self.utp_edit.toPlainText())
        self.local_cfg.save()
