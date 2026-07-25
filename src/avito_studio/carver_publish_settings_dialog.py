"""One-time, user-facing setup of the CARVER Avito feed."""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from avito_studio.carver_price_file import import_carver_price, validate_carver_price
from avito_studio.atomic_io import atomic_write_text
from avito_studio.local_config import LocalConfig
from avito_studio.ui_components import (
    FormSection,
    dialog_footer,
    dialog_header,
    get_open_file_name,
    role_button,
)

ROUNDING_OPTIONS = (
    ("Без округления", "none"),
    ("До ближайших 10 ₽", "up_to_10"),
    ("До ближайших 90 ₽", "up_to_90"),
    ("До ближайших 100 ₽", "up_to_100"),
)


class CarverPublishSettingsDialog(QDialog):
    """Styled setup dialog; it never performs an external publication itself."""

    def __init__(self, local_cfg: LocalConfig, parent=None):
        super().__init__(parent)
        self.local_cfg = local_cfg
        self._pending_price_path: Path | None = None
        values = local_cfg.get_publication_settings()
        self.setWindowTitle("Настройка публикации CARVER")
        self.resize(700, 650)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.dialog_page = QWidget(self, objectName="dialogPage")
        shell.addWidget(self.dialog_page)
        page_layout = QVBoxLayout(self.dialog_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(dialog_header(
            "Настройка публикации CARVER",
            "Заполняется один раз для профиля. Следующие прайсы будут собираться в фид автоматически.",
            parent=self.dialog_page,
        ))

        scroll = QScrollArea(self.dialog_page)
        scroll.setWidgetResizable(True)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 18, 22, 18)
        body_layout.setSpacing(14)

        source_section = FormSection(
            "Прайс CARVER",
            "Выбранный Excel сначала проверяется, затем копируется в локальное хранилище приложения.",
            body,
        )
        source_row = QHBoxLayout()
        self.price_path_input = QLineEdit(local_cfg.get_source_path())
        self.price_path_input.setReadOnly(True)
        self.price_path_input.setPlaceholderText("Выберите прайс Excel со встроенными фото")
        source_row.addWidget(self.price_path_input, 1)
        self.choose_price_btn = role_button("Выбрать Excel", "secondary")
        self.choose_price_btn.clicked.connect(self._choose_price_file)
        source_row.addWidget(self.choose_price_btn)
        source_section.content_layout.addLayout(source_row)
        body_layout.addWidget(source_section)

        category_section = FormSection(
            "Категория Avito",
            "Эти значения добавятся в каждое объявление генератора. Укажите точные названия из формата Автозагрузки вашего аккаунта.",
            body,
        )
        category_form = QFormLayout()
        category_form.setHorizontalSpacing(16)
        category_form.setVerticalSpacing(11)
        self.category_input = QLineEdit(values["category"])
        self.category_input.setPlaceholderText("например: Для дома и дачи")
        category_form.addRow("Категория*:", self.category_input)
        self.goods_type_input = QLineEdit(values["goods_type"])
        self.goods_type_input.setPlaceholderText("например: Садовая техника")
        category_form.addRow("Вид товара*:", self.goods_type_input)
        self.goods_subtype_input = QLineEdit(values["goods_subtype"])
        self.goods_subtype_input.setPlaceholderText("например: Генераторы")
        category_form.addRow("Подвид товара*:", self.goods_subtype_input)
        category_section.content_layout.addLayout(category_form)
        note = QLabel(
            "Приложение не подбирает категорию по названию вслепую: неверное значение Avito отклоняет. "
            "После сохранения эти поля больше не нужно вводить для каждого прайса.",
            objectName="helperText",
        )
        note.setWordWrap(True)
        category_section.content_layout.addWidget(note)
        body_layout.addWidget(category_section)

        price_section = FormSection(
            "Розничная цена",
            "Наценка применяется к закупочной цене из файла. При нулевой наценке требуется явное подтверждение.",
            body,
        )
        price_form = QFormLayout()
        price_form.setHorizontalSpacing(16)
        price_form.setVerticalSpacing(11)
        self.markup_input = QDoubleSpinBox()
        self.markup_input.setRange(0, 200)
        self.markup_input.setDecimals(1)
        self.markup_input.setSingleStep(1)
        self.markup_input.setSuffix(" %")
        self.markup_input.setValue(values["markup_pct"])
        price_form.addRow("Наценка:", self.markup_input)
        self.rounding_combo = QComboBox()
        for title, value in ROUNDING_OPTIONS:
            self.rounding_combo.addItem(title, value)
        current_rounding = values["rounding"]
        index = self.rounding_combo.findData(current_rounding)
        self.rounding_combo.setCurrentIndex(max(index, 0))
        price_form.addRow("Округление цены:", self.rounding_combo)
        price_section.content_layout.addLayout(price_form)
        self.price_confirmed = QCheckBox(
            "Цена в прайсе уже розничная — публиковать без дополнительной наценки"
        )
        self.price_confirmed.setChecked(values["price_confirmed"])
        self.price_confirmed.toggled.connect(self._update_pricing_hint)
        self.markup_input.valueChanged.connect(self._update_pricing_hint)
        price_section.content_layout.addWidget(self.price_confirmed)
        self.pricing_hint = QLabel(objectName="helperText")
        self.pricing_hint.setWordWrap(True)
        price_section.content_layout.addWidget(self.pricing_hint)
        body_layout.addWidget(price_section)

        next_section = FormSection(
            "Дальше — без ручной настройки",
            "1. «Обновить каталог» читает Excel.  2. Отметьте позиции.  3. «Взять фото из прайса».  4. «Опубликовать» соберёт и отправит XML-фид.",
            body,
        )
        body_layout.addWidget(next_section)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        page_layout.addWidget(scroll, 1)

        self.save_btn = role_button("Сохранить настройки", "primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._validate_and_accept)
        cancel_btn = role_button("Отмена", "secondary")
        cancel_btn.clicked.connect(self.reject)
        page_layout.addWidget(dialog_footer([cancel_btn, self.save_btn], parent=self.dialog_page))
        self._update_pricing_hint()

    def _update_pricing_hint(self, *_args) -> None:
        has_markup = self.markup_input.value() > 0
        self.price_confirmed.setEnabled(not has_markup)
        if has_markup:
            self.price_confirmed.setChecked(False)
            self.pricing_hint.setText("Готово: фид рассчитает розничную цену с указанной наценкой.")
        elif self.price_confirmed.isChecked():
            self.pricing_hint.setText("Подтверждено: цена из прайса будет считаться конечной розничной ценой.")
        else:
            self.pricing_hint.setText(
                "Публикация останется заблокированной, пока не укажете наценку или не подтвердите цену прайса."
            )

    def _choose_price_file(self) -> None:
        selected, _ = get_open_file_name(
            self,
            "Выбрать прайс CARVER",
            self.price_path_input.text(),
            "Excel (*.xlsx)",
        )
        if not selected:
            return
        try:
            candidate = Path(selected).resolve()
            count = validate_carver_price(candidate)
        except Exception as exc:  # noqa: BLE001 - UI boundary must report malformed Excel
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Прайс не принят", str(exc))
            return
        self._pending_price_path = candidate
        self.price_path_input.setText(str(candidate))
        self.pricing_hint.setText(
            f"Прайс проверен: {count} позиций и встроенные фото найдены. "
            "Файл будет установлен только после «Сохранить настройки»."
        )

    def _validate_and_accept(self) -> None:
        if not self.price_path_input.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Выберите прайс", "Сначала выберите и проверьте Excel CARVER.")
            return
        configured = Path(self.price_path_input.text().strip()).expanduser()
        bridge_root = self.local_cfg.path.resolve().parent.parent
        if not configured.is_absolute():
            configured = bridge_root / configured
        installed = bridge_root / "runtime" / "carver" / "current.xlsx"
        if self._pending_price_path is None and (
            not configured.is_file()
            or configured.resolve() != installed.resolve(strict=False)
        ):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Выберите прайс",
                "Сохранённый XLSX-прайс не найден. Выберите свежий файл CARVER.",
            )
            return
        if (not self.category_input.text().strip()
                or not self.goods_type_input.text().strip()
                or not self.goods_subtype_input.text().strip()):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Заполните категорию",
                "Для Автозагрузки нужны категория, вид и подвид товара Avito.",
            )
            return
        if self.markup_input.value() <= 0 and not self.price_confirmed.isChecked():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Подтвердите цену",
                "Укажите наценку больше 0 % или подтвердите, что цена из прайса уже розничная.",
            )
            return
        self.accept()

    def save(self) -> None:
        """Save only after the dialog has passed its local validation."""
        old_data = deepcopy(self.local_cfg.data)
        old_text = self.local_cfg.path.read_text(encoding="utf-8")
        committed_path: Path | None = None
        bridge_root = self.local_cfg.path.resolve().parent.parent
        target = bridge_root / "runtime" / "carver" / "current.xlsx"
        source_is_target = (
            self._pending_price_path is not None
            and self._pending_price_path.resolve() == target.resolve(strict=False)
        )
        backup: Path | None = None
        if self._pending_price_path is not None and target.exists() and not source_is_target:
            backup = target.with_name(f".current.backup.{uuid4().hex}.xlsx")
            os.replace(target, backup)
        try:
            if self._pending_price_path is not None:
                committed_path, _count = import_carver_price(
                    self._pending_price_path, bridge_root)
            self.local_cfg.set_publication_settings(
                category=self.category_input.text(),
                goods_type=self.goods_type_input.text(),
                goods_subtype=self.goods_subtype_input.text(),
                markup_pct=self.markup_input.value(),
                rounding=str(self.rounding_combo.currentData()),
                price_confirmed=self.price_confirmed.isChecked(),
            )
            source_path = committed_path or (
                Path(self.price_path_input.text())
                if self.price_path_input.text().strip()
                else None
            )
            if source_path is not None:
                if not source_path.is_absolute():
                    source_path = bridge_root / source_path
                self.local_cfg.set_source_path(
                    source_path,
                    relative_to=bridge_root,
                )
            self.local_cfg.save()
        except Exception:
            self.local_cfg.data = old_data
            try:
                if self.local_cfg.path.read_text(encoding="utf-8") != old_text:
                    atomic_write_text(self.local_cfg.path, old_text)
                if committed_path is not None and not source_is_target:
                    committed_path.unlink(missing_ok=True)
                if backup is not None:
                    os.replace(backup, target)
                    backup = None
            except Exception as rollback_error:
                raise RuntimeError(
                    "Не удалось сохранить настройки CARVER и полностью "
                    f"восстановить предыдущие файлы. Резервная копия: {backup}"
                ) from rollback_error
            raise
        if backup is not None:
            backup.unlink(missing_ok=True)
        self._pending_price_path = None
        if committed_path is not None:
            self.price_path_input.setText(str(committed_path))
