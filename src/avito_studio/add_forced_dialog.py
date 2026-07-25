"""Два безопасных сценария ручного добавления в Avito:
1) существующий товар Oasis по внутреннему НС-коду (force_include);
2) полностью новый товар без записи поставщика (catalog.manual_products).
Оба сценария сначала загружают фото, затем атомарно меняют локальный YAML. Внешняя публикация
происходит только отдельной кнопкой главного окна с подтверждением."""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from avito_studio.atomic_io import atomic_write_text
from avito_studio.local_config import LocalConfig
from avito_studio.manual_product_forms import (
    FieldSpec,
    appliance_groups,
    form_spec,
    serialize_manual_product,
    suggested_characteristics,
)
from avito_studio.photo_upload import is_safe_nc_code
from avito_studio.profiles import PROFILES, Profile
from avito_studio.ui_components import (
    FormSection,
    dialog_footer,
    dialog_header,
    get_open_file_name,
    role_button,
)

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
    digest = hashlib.sha1(
        signature.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:10]
    token = model_hint(title) or "product"
    stem = re.sub(r"[^a-z0-9]+", "-", token.lower()).strip("-") or "product"
    return f"manual-{stem}-{digest}"


class AddForcedProductDialog(QDialog):
    def __init__(self, local_cfg: LocalConfig, ssh,
                 profile: Profile = PROFILES[0], parent=None):
        super().__init__(parent)
        self.local_cfg = local_cfg
        self.ssh = ssh
        self.profile = profile
        self.form_spec = form_spec(profile.key)
        self._new_photo_path: Path | None = None
        self.setWindowTitle("Добавить товар вручную")
        self.resize(760, 760)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.dialog_page = QWidget(self, objectName="dialogPage")
        shell.addWidget(self.dialog_page)
        page_layout = QVBoxLayout(self.dialog_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(
            dialog_header(
                "Добавить товар вручную",
                "Добавьте позицию из каталога поставщика или создайте новую карточку без кода.",
                parent=self.dialog_page,
            )
        )

        scroll = QScrollArea(self.dialog_page)
        scroll.setWidgetResizable(True)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 18, 22, 18)
        body_layout.setSpacing(14)

        mode_section = FormSection(
            "Способ добавления",
            "Выберите сценарий — набор обязательных полей изменится автоматически.",
            body,
        )

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("helperText")
        self.profile_banner = QLabel(f"Активный профиль: <b>{profile.label}</b>")
        self.profile_banner.setObjectName("profileContext")
        self.profile_banner.setWordWrap(True)
        mode_section.content_layout.addWidget(self.profile_banner)
        mode_section.content_layout.addWidget(self.hint)

        self.tabs = QTabWidget()
        existing_tab = QWidget()
        form = QFormLayout(existing_tab)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(11)

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
        if self.form_spec.allow_nc_code:
            self.tabs.addTab(existing_tab, "Есть НС-код")

        manual_tab = QWidget()
        manual_form = QFormLayout(manual_tab)
        manual_form.setContentsMargins(16, 16, 16, 16)
        manual_form.setHorizontalSpacing(16)
        manual_form.setVerticalSpacing(11)
        self.manual_brand_field = QLineEdit()
        self.manual_brand_field.setText(self.form_spec.brand_default)
        self.manual_brand_field.setPlaceholderText("например: ROYAL CLIMA")
        manual_form.addRow(
            "Бренд:" if self.profile.key == "wreaths" else "Бренд*:",
            self.manual_brand_field,
        )
        self.manual_title_field = QLineEdit()
        self.manual_title_field.setPlaceholderText("модель или полное название товара")
        manual_form.addRow("Модель / название*:", self.manual_title_field)
        self.manual_series_field = QLineEdit()
        self.manual_series_field.setPlaceholderText("серия или линейка — если есть")
        manual_form.addRow("Серия*:" if self.form_spec.series_required else "Серия / линейка:",
                           self.manual_series_field)

        self.profile_fields: dict[str, QWidget] = {}
        for field in self.form_spec.fields:
            widget = self._create_profile_field(field)
            self.profile_fields[field.key] = widget
            label = field.label + ("*:" if field.required else ":")
            manual_form.addRow(label, widget)

        self.manual_price_field = QSpinBox()
        self.manual_price_field.setRange(0, 10_000_000)
        self.manual_price_field.setSuffix(" ₽")
        manual_form.addRow("Финальная цена*:", self.manual_price_field)
        self.manual_stock_field = QSpinBox()
        self.manual_stock_field.setRange(1, 100_000)
        self.manual_stock_field.setValue(1)
        manual_form.addRow("Количество*:", self.manual_stock_field)

        characteristics = QWidget()
        characteristics_layout = QVBoxLayout(characteristics)
        characteristics_layout.setContentsMargins(0, 0, 0, 0)
        characteristics_layout.setSpacing(6)
        self.characteristics_table = QTableWidget(0, 2)
        self.characteristics_table.setObjectName("characteristicsTable")
        self.characteristics_table.setHorizontalHeaderLabels(["Характеристика", "Значение"])
        self.characteristics_table.horizontalHeader().setStretchLastSection(True)
        self.characteristics_table.setMinimumHeight(150)
        characteristics_layout.addWidget(self.characteristics_table)
        characteristic_buttons = QHBoxLayout()
        self.add_characteristic_btn = role_button("+ Добавить строку", "secondary")
        self.remove_characteristic_btn = role_button("Удалить строку", "secondary")
        self.add_characteristic_btn.clicked.connect(self._add_characteristic_row)
        self.remove_characteristic_btn.clicked.connect(self._remove_characteristic_row)
        characteristic_buttons.addWidget(self.add_characteristic_btn)
        characteristic_buttons.addWidget(self.remove_characteristic_btn)
        characteristic_buttons.addStretch(1)
        characteristics_layout.addLayout(characteristic_buttons)
        manual_form.addRow("Характеристики:", characteristics)

        self._manual_tab_index = self.tabs.addTab(
            manual_tab, "Товара нет в базе" if self.form_spec.allow_nc_code else "Новый товар")
        mode_section.content_layout.addWidget(self.tabs)
        body_layout.addWidget(mode_section)

        self.manual_category_combo = self.profile_fields.get("product_type")
        self.manual_btu_field = self.profile_fields.get("btu")
        self.manual_inverter_box = self.profile_fields.get("inverter")

        for field in (self.manual_brand_field, self.manual_title_field,
                      self.manual_series_field):
            field.textChanged.connect(self._update_save_enabled)
        self.manual_price_field.valueChanged.connect(self._update_save_enabled)
        self.manual_stock_field.valueChanged.connect(self._update_save_enabled)
        for key, widget in self.profile_fields.items():
            self._connect_profile_field(key, widget)
        self.characteristics_table.itemChanged.connect(self._update_save_enabled)
        self.tabs.currentChanged.connect(self._on_mode_changed)
        self._seed_characteristics()

        media_section = FormSection(
            "Фото и содержание карточки",
            "Для нового товара без кода фотография обязательна. Для товара с НС-кодом — по желанию.",
            body,
        )
        photo_row = QHBoxLayout()
        photo_row.setSpacing(10)
        self.photo_label = QLabel("(нет фото)")
        self.photo_label.setObjectName("photoFileName")
        self.photo_label.setWordWrap(True)
        self.photo_btn = role_button("Выбрать файл…", "secondary")
        self.photo_btn.clicked.connect(self._choose_photo)
        photo_row.addWidget(self.photo_label, 1)
        photo_row.addWidget(self.photo_btn)
        photo_form = QFormLayout()
        photo_form.setHorizontalSpacing(16)
        photo_form.setVerticalSpacing(11)
        photo_form.addRow("Фото товара:", photo_row)
        media_section.content_layout.addLayout(photo_form)

        utp_label = QLabel(
            "Описание / особенности товара (необязательно)", objectName="fieldLabel"
        )
        media_section.content_layout.addWidget(utp_label)
        self.utp_edit = QTextEdit()
        self.utp_edit.setPlaceholderText(
            "Оставьте пустым — фотоагент возьмёт стандартный текст после публикации.")
        self.utp_edit.setMinimumHeight(82)
        self.utp_edit.setMaximumHeight(110)
        media_section.content_layout.addWidget(self.utp_edit)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("helperText")
        media_section.content_layout.addWidget(self.note)
        body_layout.addWidget(media_section)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        page_layout.addWidget(scroll, 1)

        self.save_btn = role_button("Добавить товар", "primary")
        self.save_btn.setDefault(True)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._validate_and_accept)
        self.cancel_btn = role_button("Отмена", "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        page_layout.addWidget(
            dialog_footer([self.cancel_btn, self.save_btn], parent=self.dialog_page)
        )
        self._on_mode_changed(0)

    def _create_profile_field(self, field: FieldSpec) -> QWidget:
        if field.kind == "combo":
            widget = QComboBox()
            choices = field.choices
            if self.profile.key == "appliances" and field.key == "group":
                choices = tuple((value, value) for value in appliance_groups(self.local_cfg))
            if not choices:
                choices = (("Нет доступных вариантов", ""),)
            for label, value in choices:
                widget.addItem(label, value)
            return widget
        if field.kind == "int":
            widget = QSpinBox()
            widget.setRange(0, 1_000_000)
            widget.setSuffix(field.suffix)
            return widget
        if field.kind == "float":
            widget = QDoubleSpinBox()
            widget.setRange(0, 1_000_000)
            widget.setDecimals(2)
            widget.setSingleStep(0.1)
            widget.setSuffix(field.suffix)
            return widget
        if field.kind == "bool":
            return QCheckBox("Инверторный компрессор" if field.key == "inverter" else field.label)
        widget = QLineEdit()
        if field.default:
            widget.setText(str(field.default))
        return widget

    def _connect_profile_field(self, key: str, widget: QWidget) -> None:
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(
                self._on_appliance_group_changed if key == "group"
                else self._update_save_enabled)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._update_save_enabled)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self._update_save_enabled)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self._update_save_enabled)

    def _add_characteristic_row(self, name: str = "", value: str = "") -> None:
        row = self.characteristics_table.rowCount()
        self.characteristics_table.insertRow(row)
        self.characteristics_table.setItem(row, 0, QTableWidgetItem(name))
        self.characteristics_table.setItem(row, 1, QTableWidgetItem(value))

    def _remove_characteristic_row(self) -> None:
        row = self.characteristics_table.currentRow()
        if row < 0:
            row = self.characteristics_table.rowCount() - 1
        if row >= 0:
            self.characteristics_table.removeRow(row)
        self._update_save_enabled()

    def _seed_characteristics(self) -> None:
        group = ""
        group_widget = self.profile_fields.get("group")
        if isinstance(group_widget, QComboBox):
            group = str(group_widget.currentData() or "")
        existing = {
            (self.characteristics_table.item(row, 0).text() if
             self.characteristics_table.item(row, 0) else "").strip().casefold()
            for row in range(self.characteristics_table.rowCount())
        }
        self.characteristics_table.blockSignals(True)
        try:
            for name in suggested_characteristics(self.profile.key, group):
                if name.casefold() not in existing:
                    self._add_characteristic_row(name)
        finally:
            self.characteristics_table.blockSignals(False)

    def _on_appliance_group_changed(self, *_args) -> None:
        self._seed_characteristics()
        self._update_save_enabled()

    def _profile_values(self) -> dict:
        values = {}
        for key, widget in self.profile_fields.items():
            if isinstance(widget, QComboBox):
                values[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                values[key] = widget.value()
            elif isinstance(widget, QLineEdit):
                values[key] = widget.text().strip()
        return values

    def _characteristic_rows(self) -> list[tuple[str, str]]:
        rows = []
        for row in range(self.characteristics_table.rowCount()):
            name_item = self.characteristics_table.item(row, 0)
            value_item = self.characteristics_table.item(row, 1)
            rows.append((name_item.text() if name_item else "",
                         value_item.text() if value_item else ""))
        return rows

    def _manual_spec(self, photos: list[str] | None = None) -> dict:
        if photos is None:
            photos = [str(self._new_photo_path)] if self._new_photo_path else []
        common = {
            "brand": self.manual_brand_field.text(),
            "title": self.manual_title_field.text(),
            "series": self.manual_series_field.text(),
            "price": self.manual_price_field.value(),
            "stock": self.manual_stock_field.value(),
            "photos": photos,
            "description": self.utp_edit.toPlainText(),
        }
        return serialize_manual_product(
            self.profile.key, common, self._profile_values(), self._characteristic_rows())

    def _manual_mode(self) -> bool:
        return self.tabs.currentIndex() == self._manual_tab_index

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
        if self._manual_mode():
            try:
                self._manual_spec()
            except (TypeError, ValueError):
                valid = False
            else:
                valid = True
            self.save_btn.setEnabled(valid)
            return

        nc_code = self.nc_field.text().strip()
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
        path, _ = get_open_file_name(
            self, "Выбрать фото", "", "Изображения (*.jpg *.jpeg *.png)"
        )
        if path:
            self._new_photo_path = Path(path)
            self.photo_label.setText(path)
            self._update_save_enabled()

    def _validate_and_accept(self) -> None:
        if self._manual_mode():
            try:
                spec = self._manual_spec()
                manual_id = make_manual_id(
                    spec["brand"], spec["title"], spec["series"])
                self._ensure_product_id_is_new(manual_id, manual=True)
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(
                    self, "Заполните карточку",
                    str(exc))
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
        try:
            self._ensure_product_id_is_new(nc_code, manual=False)
        except ValueError as exc:
            QMessageBox.warning(self, "Товар уже добавлен", str(exc))
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
        original_data = deepcopy(self.local_cfg.data)
        original_text = self.local_cfg.path.read_text(encoding="utf-8")
        try:
            if self._manual_mode():
                self._save_manual_product()
                return
            self._save_existing_product()
        except Exception:
            self.local_cfg.data = original_data
            try:
                if self.local_cfg.path.read_text(encoding="utf-8") != original_text:
                    atomic_write_text(self.local_cfg.path, original_text)
            except OSError:
                # Preserve the actionable original error.  Atomic LocalConfig
                # writes keep the previous YAML unless the filesystem itself
                # is unavailable.
                pass
            raise

    def _save_manual_product(self) -> None:
        spec = self._manual_spec()
        manual_id = make_manual_id(spec["brand"], spec["title"], spec["series"])
        self._ensure_product_id_is_new(manual_id, manual=True)
        from avito_studio.workers import upload_photo_blocking
        photo_url = upload_photo_blocking(
            self.ssh, self._new_photo_path, manual_id, parent=self)
        spec["photos"] = [photo_url]
        self.local_cfg.add_manual_product(manual_id, spec)
        self.local_cfg.save()

    def _save_existing_product(self) -> None:
        nc = self.nc_field.text().strip()
        if not is_internal_nc_code(nc):
            raise ValueError(
                "Внутренний код товара должен быть указан без пробелов и полного названия")
        self._ensure_product_id_is_new(nc, manual=False)

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

    def _ensure_product_id_is_new(self, product_id: str, *, manual: bool) -> None:
        """Reject duplicate IDs before the first irreversible photo upload.

        A repeated add is an edit, not a new product.  Checking both catalog
        namespaces also protects hand-edited YAML from an ambiguous ID that
        would otherwise overwrite a remote photo before the local save fails.
        """
        duplicate_manual = self.local_cfg.get_manual_product(product_id) is not None
        duplicate_forced = self.local_cfg.has_force_include(product_id)
        if not duplicate_manual and not duplicate_forced:
            return
        kind = "ручной товар" if manual else "товар с НС-кодом"
        raise ValueError(
            f"Такой {kind} уже существует. Откройте его в каталоге для редактирования."
        )
