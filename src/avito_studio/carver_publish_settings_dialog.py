"""One-time, user-facing setup of the CARVER Avito feed."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from avito_studio.local_config import LocalConfig
from avito_studio.ui_components import FormSection, dialog_footer, dialog_header, role_button


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

    def _validate_and_accept(self) -> None:
        if not self.category_input.text().strip() or not self.goods_type_input.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Заполните категорию",
                "Для Автозагрузки нужны и категория, и вид товара Avito.",
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
        self.local_cfg.set_publication_settings(
            category=self.category_input.text(),
            goods_type=self.goods_type_input.text(),
            markup_pct=self.markup_input.value(),
            rounding=str(self.rounding_combo.currentData()),
            price_confirmed=self.price_confirmed.isChecked(),
        )
        self.local_cfg.save()
