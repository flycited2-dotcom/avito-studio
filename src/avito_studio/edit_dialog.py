"""Диалог редактирования серии: цена (любая серия, с кнопкой возврата к авторасчёту),
ручное фото (manual_photos), УТП карточки, описание серии. «Сохранить» пишет изменения ЛОКАЛЬНО
(config.yaml, avito-descriptions/) — на сервер они уйдут отдельным нажатием «Опубликовать»."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QTextEdit, QPushButton,
                               QFileDialog, QLabel, QHBoxLayout, QSpinBox)
from avito_studio.catalog_service import CatalogRow, leading_price
from avito_studio.local_config import LocalConfig
from avito_studio import description_store
from avito_studio.workers import GenerateCardWorker, run_in_thread


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
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        form = QFormLayout()

        self.price_field = QSpinBox()
        self.price_field.setRange(0, 10_000_000)
        self.price_field.setSuffix(" ₽")
        self.reset_price_btn: QPushButton | None = None
        self._reset_price = False
        price_row = QHBoxLayout()
        price_row.addWidget(self.price_field, 1)
        if row.forced:
            self.price_field.setValue(local_cfg.get_force_price(row.representative_nc) or 0)
        else:
            override = local_cfg.get_manual_price(row.representative_nc)
            self.price_field.setValue(override if override is not None else leading_price(row.price_range) or 0)
            self.price_field.setToolTip(
                "По умолчанию — авторасчёт (опт + наценка). Можно задать свою цену вручную.")
            # у товара «под заказ» нет авторасчёта — кнопка сброса только для обычных серий
            self.reset_price_btn = QPushButton("Вернуть авторасчёт")
            self.reset_price_btn.setToolTip(
                "Снять ручную цену: после «Опубликовать» цена снова считается автоматически (опт + наценка).")
            self.reset_price_btn.clicked.connect(self._toggle_price_reset)
            price_row.addWidget(self.reset_price_btn)
        self._initial_price_shown = self.price_field.value()
        form.addRow("Цена:", price_row)

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
            "Заполните, если хотите подсветить что-то особенное. Очистите поле — вернётся автотекст.")
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
        buttons.addStretch()
        save_btn = QPushButton("Сохранить")
        save_btn.setProperty("accent", True)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

    def _toggle_price_reset(self) -> None:
        self._reset_price = not self._reset_price
        self.price_field.setEnabled(not self._reset_price)
        self.reset_price_btn.setText("Оставить ручную цену" if self._reset_price
                                     else "Вернуть авторасчёт")

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
        elif self._reset_price:
            self.local_cfg.remove_manual_price(self.row.representative_nc)
        elif self.price_field.value() != self._initial_price_shown:
            # override пишем ТОЛЬКО если значение реально поменяли — иначе при каждом открытии+
            # сохранении диалога без правки цены плодили бы записи manual_price_override.
            self.local_cfg.set_manual_price(self.row.representative_nc, self.price_field.value())
        if self._new_photo_path:
            from avito_studio.workers import upload_photo_blocking
            url = upload_photo_blocking(self.ssh, self._new_photo_path,
                                        self.row.representative_nc, parent=self)
            self.local_cfg.set_manual_photo(self.row.representative_nc, url)
            # Профиль бытовой техники стартует с защитным sentinel'ом: без фото не
            # публикуется ничего. Ручное фото = явная готовность конкретной позиции.
            if "__none__" in self.local_cfg.selected_series():
                self.local_cfg.set_selected(self.row.key, True)
                self.row.selected = True
            self.row.has_card = True
        if self.utp_edit.toPlainText() != self._initial_utp_shown:
            # пишем override ТОЛЬКО при реальном изменении; очищенное поле = «вернуть автотекст»
            # (снимаем override, а не пишем пустую строку в config.yaml)
            text = self.utp_edit.toPlainText().strip()
            if text:
                self.local_cfg.set_card_brief(self.row.representative_nc, self.utp_edit.toPlainText())
            else:
                self.local_cfg.remove_card_brief(self.row.representative_nc)
        self.local_cfg.save()
        if self.description_edit.toPlainText() != self._initial_description_shown:
            # аналогично: не плодим пустые файлы-заглушки в avito-descriptions/ на каждое
            # открытие+сохранение карточки без правки описания.
            description_store.save_description(self.bridge_root, self.row.key,
                                               self.description_edit.toPlainText())
