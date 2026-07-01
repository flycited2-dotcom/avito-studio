"""Форма «товар под заказ»: артикул (должен существовать как продукт у поставщика в БД oasis,
просто без остатка на складе) + цена + опционально имя серии. Пишет запись в LocalConfig
(force_include) — «Опубликовать» в главном окне уже разберётся с деплоем."""
from __future__ import annotations
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton,
                               QVBoxLayout, QHBoxLayout)
from avito_studio.local_config import LocalConfig


class AddForcedProductDialog(QDialog):
    def __init__(self, local_cfg: LocalConfig, parent=None):
        super().__init__(parent)
        self.local_cfg = local_cfg
        self.setWindowTitle("Добавить товар под заказ")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.nc_field = QLineEdit()
        self.nc_field.setPlaceholderText("напр. НС-1690797")
        self.nc_field.textChanged.connect(self._update_save_enabled)
        form.addRow("Артикул:", self.nc_field)

        self.price_field = QSpinBox()
        self.price_field.setRange(0, 10_000_000)
        self.price_field.setSuffix(" ₽")
        form.addRow("Цена:", self.price_field)

        self.series_field = QLineEdit()
        self.series_field.setPlaceholderText("необязательно — своё объявление, а не общая серия")
        form.addRow("Имя серии:", self.series_field)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Добавить")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _update_save_enabled(self, text: str) -> None:
        self.save_btn.setEnabled(bool(text.strip()))

    def save(self) -> None:
        """Вызывается ПОСЛЕ exec()==Accepted (см. main_window._open_add_forced_dialog)."""
        self.local_cfg.add_force_include(
            self.nc_field.text().strip(), self.price_field.value(),
            series=self.series_field.text().strip() or None)
        self.local_cfg.save()
