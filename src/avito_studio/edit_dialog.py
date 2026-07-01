"""Диалог редактирования серии: цена (только для товаров «под заказ» — force_include),
ручное фото (manual_photos), описание серии. «Сохранить» пишет изменения ЛОКАЛЬНО (config.yaml,
avito-descriptions/) — на сервер они уйдут отдельным нажатием «Опубликовать» в главном окне."""
from __future__ import annotations
import re
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QTextEdit, QPushButton,
                               QFileDialog, QLabel, QHBoxLayout, QSpinBox)
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig
from avito_studio import description_store


def _leading_price(price_range: str) -> int | None:
    """Первое число из строки вида "25990–27990 ₽" / "19990 ₽" / "—" — для информационного
    показа авторасчитанной цены в задизейбленном поле (не forced-серии её не редактируют)."""
    m = re.match(r"(\d+)", price_range)
    return int(m.group(1)) if m else None


class EditSeriesDialog(QDialog):
    def __init__(self, row: CatalogRow, bridge_root: Path, local_cfg: LocalConfig, ssh, parent=None):
        super().__init__(parent)
        self.row = row
        self.bridge_root = Path(bridge_root)
        self.local_cfg = local_cfg
        self.ssh = ssh
        self._new_photo_path: Path | None = None
        self.setWindowTitle(f"{row.brand} {row.series}")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.price_field = QSpinBox()
        self.price_field.setRange(0, 10_000_000)
        self.price_field.setSuffix(" ₽")
        if row.forced:
            self.price_field.setValue(local_cfg.get_force_price(row.representative_nc) or 0)
        else:
            self.price_field.setValue(_leading_price(row.price_range) or 0)
            self.price_field.setEnabled(False)
            self.price_field.setToolTip(
                "Авторасчёт (опт + наценка) — редактируется только для товаров «под заказ»")
        form.addRow("Цена:", self.price_field)

        photo_row = QHBoxLayout()
        self.photo_label = QLabel(local_cfg.get_manual_photo(row.representative_nc) or "(нет ручного фото)")
        photo_btn = QPushButton("Выбрать файл…")
        photo_btn.clicked.connect(self._choose_photo)
        photo_row.addWidget(self.photo_label)
        photo_row.addWidget(photo_btn)
        form.addRow("Фото:", photo_row)
        layout.addLayout(form)

        layout.addWidget(QLabel("Описание:"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(description_store.get_description(self.bridge_root, row.key))
        layout.addWidget(self.description_edit)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _choose_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать фото", "", "Изображения (*.jpg *.jpeg *.png)")
        if path:
            self._new_photo_path = Path(path)
            self.photo_label.setText(path)

    def save(self) -> None:
        """Применяет правки. Вызывается ПОСЛЕ exec()==Accepted (см. main_window._open_edit_dialog).
        Загрузка фото — сетевой вызов; при заметных задержках вынести в QThread (см. workers.py),
        пока не требуется (маленький файл, диалог модальный — пользователь и так ждёт)."""
        if self.row.forced:
            self.local_cfg.set_force_price(self.row.representative_nc, self.price_field.value())
        if self._new_photo_path:
            from avito_studio.photo_upload import upload_manual_photo
            url = upload_manual_photo(self.ssh, self._new_photo_path, self.row.representative_nc)
            self.local_cfg.set_manual_photo(self.row.representative_nc, url)
        self.local_cfg.save()
        description_store.save_description(self.bridge_root, self.row.key,
                                           self.description_edit.toPlainText())
