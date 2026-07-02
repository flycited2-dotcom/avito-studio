"""Форма ручного добавления товара в выгрузку Avito: артикул поставщика (должен существовать как
продукт в БД oasis, просто без остатка на складе) + цена + опционально имя серии + фото/УТП.
Фото и УТП привязаны к артикулу и грузятся сразу — публикация для них не нужна. Описание для
объявления Avito привязано к КЛЮЧУ СЕРИИ (источник+бренд+серия), а источник/бренд узнаются только
из реальной записи в БД поставщика — до первой публикации студия их не знает, поэтому описание
задаётся отдельно, двойным кликом по строке после того, как товар появится в таблице.
«Опубликовать» в главном окне уже разберётся с деплоем force_include/manual_photos/manual_card_brief."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton,
                               QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QTextEdit,
                               QFileDialog)
from avito_studio.local_config import LocalConfig


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
            "Артикул поставщика (nc_code) — в основной таблице его не видно (там только бренд/серия).\n"
            "Уточните артикул в Excel-каталоге поставщика или у товароведа перед вводом.")
        hint.setWordWrap(True)
        hint.setProperty("hint", True)
        layout.addWidget(hint)

        form = QFormLayout()

        self.nc_field = QLineEdit()
        self.nc_field.setPlaceholderText("напр. НС-1690797")
        self.nc_field.textChanged.connect(self._update_save_enabled)
        form.addRow("Артикул поставщика:", self.nc_field)

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
        self.save_btn.setEnabled(bool(text.strip()))

    def _choose_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать фото", "", "Изображения (*.jpg *.jpeg *.png)")
        if path:
            self._new_photo_path = Path(path)
            self.photo_label.setText(path)

    def _validate_and_accept(self) -> None:
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
        self.local_cfg.add_force_include(nc, self.price_field.value(),
                                         series=self.series_field.text().strip() or None)
        if self._new_photo_path:
            from avito_studio.photo_upload import upload_manual_photo
            url = upload_manual_photo(self.ssh, self._new_photo_path, nc)
            self.local_cfg.set_manual_photo(nc, url)
        if self.utp_edit.toPlainText().strip():
            self.local_cfg.set_card_brief(nc, self.utp_edit.toPlainText())
        self.local_cfg.save()
