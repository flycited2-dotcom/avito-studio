"""Два безопасных сценария ручного добавления в Avito:
1) существующий товар Oasis по внутреннему НС-коду (force_include);
2) полностью новый товар без записи поставщика (catalog.manual_products).
Оба сценария сначала загружают фото, затем атомарно меняют локальный YAML. Внешняя публикация
происходит только отдельной кнопкой главного окна с подтверждением."""
from __future__ import annotations
from pathlib import Path
import hashlib
import re
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton,
                               QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QTextEdit,
                               QFileDialog, QTabWidget, QWidget, QComboBox, QCheckBox)
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


def make_manual_id(brand: str, title: str, series: str) -> str:
    """Стабильный ASCII-ID: одинаковая карточка не получит новый Avito Id после пересборки."""
    signature = "|".join(part.strip().lower() for part in (brand, title, series))
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:10]
    token = model_hint(title) or "product"
    stem = re.sub(r"[^a-z0-9]+", "-", token.lower()).strip("-") or "product"
    return f"manual-{stem}-{digest}"


class AddForcedProductDialog(QDialog):
    def __init__(self, local_cfg: LocalConfig, ssh, parent=None):
        super().__init__(parent)
        self.local_cfg = local_cfg
        self.ssh = ssh
        self._new_photo_path: Path | None = None
        self.setWindowTitle("Добавить товар вручную")
        self.resize(640, 650)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setProperty("hint", True)
        layout.addWidget(self.hint)

        self.tabs = QTabWidget()
        existing_tab = QWidget()
        form = QFormLayout(existing_tab)

        self.nc_field = QLineEdit()
        self.nc_field.setPlaceholderText("например: НС-1480532")
        self.nc_field.textChanged.connect(self._update_save_enabled)
        nc_container = QWidget()
        nc_box = QVBoxLayout(nc_container)
        nc_box.setContentsMargins(0, 0, 0, 0)
        nc_box.setSpacing(3)
        nc_box.addWidget(self.nc_field)
        self.nc_error = QLabel("")
        self.nc_error.setWordWrap(True)
        self.nc_error.setProperty("fieldError", True)
        nc_box.addWidget(self.nc_error)
        form.addRow("Внутренний код товара:", nc_container)

        self.price_field = QSpinBox()
        self.price_field.setRange(0, 10_000_000)
        self.price_field.setSuffix(" ₽")
        form.addRow("Цена:", self.price_field)

        self.series_field = QLineEdit()
        self.series_field.setPlaceholderText("необязательно — своё объявление, а не общая серия")
        form.addRow("Имя серии:", self.series_field)
        self.tabs.addTab(existing_tab, "Есть НС-код")

        manual_tab = QWidget()
        manual_form = QFormLayout(manual_tab)
        self.manual_brand_field = QLineEdit()
        self.manual_brand_field.setPlaceholderText("например: ROYAL CLIMA")
        manual_form.addRow("Бренд*:", self.manual_brand_field)
        self.manual_title_field = QLineEdit()
        self.manual_title_field.setPlaceholderText("например: RCI-GR28HN")
        manual_form.addRow("Модель / название*:", self.manual_title_field)
        self.manual_series_field = QLineEdit()
        self.manual_series_field.setPlaceholderText("например: GRIDA DC EU")
        manual_form.addRow("Серия*:", self.manual_series_field)
        self.manual_category_combo = QComboBox()
        self.manual_category_combo.addItem("Настенная сплит-система", 2)
        self.manual_category_combo.addItem("Полупромышленный кондиционер", 6)
        self.manual_category_combo.addItem("Мобильный кондиционер", 7)
        manual_form.addRow("Тип товара*:", self.manual_category_combo)
        self.manual_btu_field = QSpinBox()
        self.manual_btu_field.setRange(0, 100)
        self.manual_btu_field.setSuffix(" тыс. BTU")
        manual_form.addRow("Типоразмер*:", self.manual_btu_field)
        self.manual_price_field = QSpinBox()
        self.manual_price_field.setRange(0, 10_000_000)
        self.manual_price_field.setSuffix(" ₽")
        manual_form.addRow("Финальная цена*:", self.manual_price_field)
        self.manual_inverter_box = QCheckBox("Инверторный компрессор")
        manual_form.addRow("Исполнение:", self.manual_inverter_box)
        self.tabs.addTab(manual_tab, "Товара нет в базе")
        layout.addWidget(self.tabs)

        for field in (self.manual_brand_field, self.manual_title_field,
                      self.manual_series_field):
            field.textChanged.connect(self._update_save_enabled)
        self.manual_btu_field.valueChanged.connect(self._update_save_enabled)
        self.manual_price_field.valueChanged.connect(self._update_save_enabled)
        self.tabs.currentChanged.connect(self._on_mode_changed)

        photo_row = QHBoxLayout()
        self.photo_label = QLabel("(нет фото)")
        self.photo_btn = QPushButton("Выбрать файл…")
        self.photo_btn.clicked.connect(self._choose_photo)
        photo_row.addWidget(self.photo_label)
        photo_row.addWidget(self.photo_btn)
        layout.addLayout(photo_row)

        layout.addWidget(QLabel("УТП/характеристики для карточки (необязательно):"))
        self.utp_edit = QTextEdit()
        self.utp_edit.setPlaceholderText(
            "Оставьте пустым — фотоагент возьмёт стандартный текст после публикации.")
        self.utp_edit.setMaximumHeight(80)
        layout.addWidget(self.utp_edit)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("hint", True)
        layout.addWidget(self.note)

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
        self._on_mode_changed(0)

    def _manual_mode(self) -> bool:
        return self.tabs.currentIndex() == 1

    def _on_mode_changed(self, _index: int) -> None:
        if self._manual_mode():
            self.hint.setText(
                "Если товара нет ни в базе, ни в прайсе, заполните карточку самостоятельно. "
                "Приложение создаст постоянный технический ID; фото обязательно.")
            self.note.setText(
                "Цена считается финальной и не получает дополнительную наценку. Товар попадёт "
                "на сервер только после отдельного подтверждения «Опубликовать изменения».")
        else:
            self.hint.setText(
                "Нужен внутренний код поставщика вида НС-1480532 — не модель и не полное название.\n"
                "По этому коду сервер находит точный товар, даже если его сейчас нет на складе.")
            self.note.setText(
                "Описание можно дополнить двойным кликом по строке после обновления каталога.")
        self._update_save_enabled()

    def _update_save_enabled(self, *_args) -> None:
        nc_code = self.nc_field.text().strip()
        valid = (bool(self.manual_brand_field.text().strip())
                 and bool(self.manual_title_field.text().strip())
                 and bool(self.manual_series_field.text().strip())
                 and self.manual_btu_field.value() > 0
                 and self.manual_price_field.value() > 0
                 and self._new_photo_path is not None) if self._manual_mode() else is_internal_nc_code(nc_code)
        self.save_btn.setEnabled(valid)
        if not self._manual_mode() and nc_code and not valid:
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
            self._update_save_enabled()

    def _validate_and_accept(self) -> None:
        if self._manual_mode():
            if not self.save_btn.isEnabled():
                QMessageBox.warning(
                    self, "Заполните карточку",
                    "Для товара без кода обязательны бренд, модель, серия, типоразмер, "
                    "финальная цена и фотография.")
                return
            self.accept()
            return
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
        """Сначала фото, затем локальный YAML: при сбое не остаётся частичной записи."""
        if self._manual_mode():
            self._save_manual_product()
            return
        self._save_existing_product()

    def _save_manual_product(self) -> None:
        brand = self.manual_brand_field.text().strip()
        title = self.manual_title_field.text().strip()
        series = self.manual_series_field.text().strip()
        if not (brand and title and series and self.manual_btu_field.value() > 0
                and self.manual_price_field.value() > 0 and self._new_photo_path):
            raise ValueError("Для товара без кода заполнены не все обязательные поля")
        if self.manual_inverter_box.isChecked() and not re.search(
                r"инвертор|inverter", series, re.IGNORECASE):
            series += " Inverter"
        manual_id = make_manual_id(brand, title, series)
        from avito_studio.workers import upload_photo_blocking
        photo_url = upload_photo_blocking(
            self.ssh, self._new_photo_path, manual_id, parent=self)
        tech = {}
        if self.manual_inverter_box.isChecked():
            tech["Тип компрессора"] = "Инвертор"
        if self.utp_edit.toPlainText().strip():
            tech["Особенности"] = self.utp_edit.toPlainText().strip()
        self.local_cfg.add_manual_product(manual_id, {
            "brand": brand, "title": title, "series": series,
            "category_id": self.manual_category_combo.currentData(),
            "btu": self.manual_btu_field.value(),
            "price": self.manual_price_field.value(), "stock": 1,
            "photos": [photo_url], "tech": tech,
        })
        self.local_cfg.save()

    def _save_existing_product(self) -> None:
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
