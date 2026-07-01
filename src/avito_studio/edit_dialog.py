"""Диалог редактирования серии: цена (только для товаров «под заказ» — force_include),
ручное фото (manual_photos), описание серии. «Сохранить» пишет изменения ЛОКАЛЬНО (config.yaml,
avito-descriptions/) — на сервер они уйдут отдельным нажатием «Опубликовать» в главном окне."""
from __future__ import annotations
import re
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QTextEdit, QPushButton,
                               QFileDialog, QLabel, QHBoxLayout, QSpinBox)
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig
from avito_studio import description_store
from avito_studio.workers import GenerateCardWorker, run_in_thread


def _leading_price(price_range: str) -> int | None:
    """Первое число из строки вида "25990–27990 ₽" / "19990 ₽" / "—" — предзаполнение поля цены
    авторасчитанным значением, когда ручного override ещё нет."""
    m = re.match(r"(\d+)", price_range)
    return int(m.group(1)) if m else None


class EditSeriesDialog(QDialog):
    card_generation_done = Signal()

    def __init__(self, row: CatalogRow, bridge_root: Path, local_cfg: LocalConfig, ssh, parent=None):
        super().__init__(parent)
        self.row = row
        self.bridge_root = Path(bridge_root)
        self.local_cfg = local_cfg
        self.ssh = ssh
        self._new_photo_path: Path | None = None
        self.setWindowTitle(f"{row.brand} {row.series}")
        self.resize(600, 500)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.price_field = QSpinBox()
        self.price_field.setRange(0, 10_000_000)
        self.price_field.setSuffix(" ₽")
        if row.forced:
            self.price_field.setValue(local_cfg.get_force_price(row.representative_nc) or 0)
        else:
            override = local_cfg.get_manual_price(row.representative_nc)
            self.price_field.setValue(override if override is not None else _leading_price(row.price_range) or 0)
            self.price_field.setToolTip(
                "По умолчанию — авторасчёт (опт + наценка). Можно задать свою цену вручную.")
        self._initial_price_shown = self.price_field.value()
        form.addRow("Цена:", self.price_field)

        photo_row = QHBoxLayout()
        self.photo_label = QLabel(local_cfg.get_manual_photo(row.representative_nc) or "(нет ручного фото)")
        photo_btn = QPushButton("Выбрать файл…")
        photo_btn.clicked.connect(self._choose_photo)
        photo_row.addWidget(self.photo_label)
        photo_row.addWidget(photo_btn)
        form.addRow("Фото:", photo_row)

        card_row = QHBoxLayout()
        self.generate_card_btn = QPushButton("Сгенерировать карточку")
        self.generate_card_btn.setEnabled(not row.has_card)
        self.generate_card_btn.clicked.connect(self._generate_card)
        self.card_status_label = QLabel("Карточка есть" if row.has_card else "Карточки нет")
        card_row.addWidget(self.generate_card_btn)
        card_row.addWidget(self.card_status_label)
        form.addRow("Карточка:", card_row)
        self._threads = []

        layout.addLayout(form)

        layout.addWidget(QLabel("УТП/характеристики для карточки (необязательно):"))
        self.utp_edit = QTextEdit()
        self.utp_edit.setPlaceholderText(
            "Оставьте пустым — фотоагент возьмёт стандартный текст (бренд/тип/размер/инвертор). "
            "Заполните, если хотите подсветить что-то особенное для этого товара.")
        self.utp_edit.setMaximumHeight(80)
        self.utp_edit.setPlainText(local_cfg.get_card_brief(row.representative_nc) or "")
        self._initial_utp_shown = self.utp_edit.toPlainText()
        layout.addWidget(self.utp_edit)

        layout.addWidget(QLabel("Описание для объявления Avito (необязательно):"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Оставьте пустым — описание сгенерируется автоматически (тип/размер/площадь/выгоды). "
            "Заполните, только если хотите написать текст сами.")
        self.description_edit.setPlainText(description_store.get_description(self.bridge_root, row.key))
        self._initial_description_shown = self.description_edit.toPlainText()
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

    def _generate_card(self) -> None:
        self.generate_card_btn.setEnabled(False)
        self.card_status_label.setText("Ставлю задачу…")
        worker = GenerateCardWorker(self.ssh, self.row.key)
        self._threads.append(run_in_thread(worker, self._on_card_generated, self._on_card_failed))

    def _on_card_generated(self, output: str) -> None:
        self.card_status_label.setText(output.strip())
        self.generate_card_btn.setEnabled(True)   # можно повторить (напр. когда лимит подняли)
        self.card_generation_done.emit()

    def _on_card_failed(self, message: str) -> None:
        self.card_status_label.setText(f"Ошибка: {message}")
        self.generate_card_btn.setEnabled(True)

    def save(self) -> None:
        """Применяет правки. Вызывается ПОСЛЕ exec()==Accepted (см. main_window._open_edit_dialog).
        Загрузка фото — сетевой вызов; при заметных задержках вынести в QThread (см. workers.py),
        пока не требуется (маленький файл, диалог модальный — пользователь и так ждёт)."""
        if self.row.forced:
            self.local_cfg.set_force_price(self.row.representative_nc, self.price_field.value())
        elif self.price_field.value() != self._initial_price_shown:
            # override пишем ТОЛЬКО если значение реально поменяли — иначе при каждом открытии+
            # сохранении диалога без правки цены плодили бы записи manual_price_override.
            self.local_cfg.set_manual_price(self.row.representative_nc, self.price_field.value())
        if self._new_photo_path:
            from avito_studio.photo_upload import upload_manual_photo
            url = upload_manual_photo(self.ssh, self._new_photo_path, self.row.representative_nc)
            self.local_cfg.set_manual_photo(self.row.representative_nc, url)
        if self.utp_edit.toPlainText() != self._initial_utp_shown:
            # так же, как с ценой — пишем override ТОЛЬКО при реальном изменении, иначе открытие
            # и сохранение диалога без правки УТП засоряло бы config.yaml пустыми записями.
            self.local_cfg.set_card_brief(self.row.representative_nc, self.utp_edit.toPlainText())
        self.local_cfg.save()
        if self.description_edit.toPlainText() != self._initial_description_shown:
            # аналогично: не плодим пустые файлы-заглушки в avito-descriptions/ на каждое
            # открытие+сохранение карточки без правки описания.
            description_store.save_description(self.bridge_root, self.row.key,
                                               self.description_edit.toPlainText())
