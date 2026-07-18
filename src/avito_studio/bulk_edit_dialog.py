"""Profile-scoped bulk publication and price editor."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avito_studio.bulk_changes import (
    BulkPreview,
    BulkRequest,
    apply_bulk_preview,
    build_bulk_preview,
)
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig
from avito_studio.ui_components import FormSection, dialog_footer, dialog_header, role_button


class BulkEditDialog(QDialog):
    applied = Signal(object)

    def __init__(self, rows: list[CatalogRow], local_cfg: LocalConfig, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.local_cfg = local_cfg
        self.preview: BulkPreview | None = None
        self.setWindowTitle("Массовое изменение")
        self.resize(980, 720)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        page = QWidget(self, objectName="dialogPage")
        shell.addWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(dialog_header(
            "Массовое изменение",
            "Выберите товары текущего профиля, проверьте расчёт и сохраните изменения локально.",
            parent=page,
        ))

        body = QWidget(page)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 16, 22, 16)
        body_layout.setSpacing(12)

        products = FormSection(
            "Товары",
            "Поиск не сбрасывает уже выбранные строки. Можно собрать выбор из нескольких фильтров.",
            body,
        )
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("bulkSearch")
        self.search_input.setAccessibleName("Поиск товаров для массового изменения")
        self.search_input.setPlaceholderText("Бренд, серия или цена…")
        self.select_filtered_btn = role_button("Выбрать найденные", "secondary")
        self.select_published_btn = role_button("Выбрать публикуемые", "secondary")
        self.clear_selection_btn = role_button("Снять выбор", "ghost")
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.select_filtered_btn)
        search_row.addWidget(self.select_published_btn)
        search_row.addWidget(self.clear_selection_btn)
        products.content_layout.addLayout(search_row)

        self.products_table = QTableWidget(0, 5)
        self.products_table.setObjectName("bulkProductsTable")
        self.products_table.setAccessibleName("Товары текущего профиля")
        self.products_table.setHorizontalHeaderLabels(
            ["Выбор", "Бренд", "Товар / серия", "Цена", "Публикуется"])
        self.products_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.products_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.products_table.verticalHeader().setVisible(False)
        self.products_table.horizontalHeader().setStretchLastSection(True)
        self._populate_products()
        products.content_layout.addWidget(self.products_table)
        body_layout.addWidget(products, 2)

        operation = FormSection(
            "Операция",
            "Цена рассчитывается от текущей итоговой цены каждой модели. Защита закупочной цены включена.",
            body,
        )
        operation_row = QHBoxLayout()
        operation_row.addWidget(QLabel("Публикация:"))
        self.publication_combo = QComboBox()
        self.publication_combo.setAccessibleName("Изменение публикации")
        self.publication_combo.addItem("Не менять", "unchanged")
        self.publication_combo.addItem("Включить", "on")
        self.publication_combo.addItem("Выключить", "off")
        operation_row.addWidget(self.publication_combo)
        operation_row.addWidget(QLabel("Цена:"))
        self.price_mode_combo = QComboBox()
        self.price_mode_combo.setAccessibleName("Режим изменения цены")
        self.price_mode_combo.addItem("Не менять", "unchanged")
        self.price_mode_combo.addItem("Изменить на %", "percent")
        self.price_mode_combo.addItem("Прибавить / вычесть ₽", "amount")
        self.price_mode_combo.addItem("Установить цену", "fixed")
        self.price_mode_combo.addItem("Вернуть авторасчёт", "reset")
        operation_row.addWidget(self.price_mode_combo)
        self.price_value_input = QDoubleSpinBox()
        self.price_value_input.setAccessibleName("Значение изменения цены")
        self.price_value_input.setRange(-9_999_999, 10_000_000)
        self.price_value_input.setDecimals(2)
        self.price_value_input.setSingleStep(1)
        self.price_value_input.setEnabled(False)
        operation_row.addWidget(self.price_value_input)
        operation_row.addStretch(1)
        operation.content_layout.addLayout(operation_row)
        body_layout.addWidget(operation)

        preview_section = FormSection(
            "Предварительный результат",
            "Сохранение ниже не отправляет данные на сервер или Avito.",
            body,
        )
        self.preview_label = QLabel("Выберите товары и операцию", objectName="helperText")
        self.preview_label.setWordWrap(True)
        preview_section.content_layout.addWidget(self.preview_label)
        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setObjectName("bulkPreviewTable")
        self.preview_table.setAccessibleName("Предварительный список изменений")
        self.preview_table.setHorizontalHeaderLabels(["Объект", "Было", "Станет", "Результат"])
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        preview_section.content_layout.addWidget(self.preview_table)
        body_layout.addWidget(preview_section, 1)
        layout.addWidget(body, 1)

        self.apply_btn = role_button("Применить локально", "primary")
        self.apply_btn.setEnabled(False)
        self.apply_btn.setDefault(False)
        cancel_btn = role_button("Отмена", "secondary")
        cancel_btn.clicked.connect(self.reject)
        self.apply_btn.clicked.connect(self._apply)
        layout.addWidget(dialog_footer([cancel_btn, self.apply_btn], parent=page))

        self.search_input.textChanged.connect(self._filter_products)
        self.select_filtered_btn.clicked.connect(self._select_filtered)
        self.select_published_btn.clicked.connect(self._select_published)
        self.clear_selection_btn.clicked.connect(self._clear_selection)
        self.products_table.itemChanged.connect(self._refresh_preview)
        self.publication_combo.currentIndexChanged.connect(self._refresh_preview)
        self.price_mode_combo.currentIndexChanged.connect(self._price_mode_changed)
        self.price_value_input.valueChanged.connect(self._refresh_preview)

    def _populate_products(self) -> None:
        self.products_table.blockSignals(True)
        self.products_table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            selected = QTableWidgetItem()
            selected.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            selected.setCheckState(Qt.Unchecked)
            selected.setData(Qt.UserRole, row.key)
            selected.setData(Qt.UserRole + 1, row.selected)
            self.products_table.setItem(index, 0, selected)
            self.products_table.setItem(index, 1, QTableWidgetItem(row.brand))
            self.products_table.setItem(index, 2, QTableWidgetItem(row.series))
            self.products_table.setItem(index, 3, QTableWidgetItem(row.price_range))
            self.products_table.setItem(
                index, 4, QTableWidgetItem("Да" if row.selected else "Нет"))
        self.products_table.blockSignals(False)
        self.products_table.resizeColumnsToContents()

    def selected_keys(self) -> tuple[str, ...]:
        return tuple(
            str(item.data(Qt.UserRole))
            for row in range(self.products_table.rowCount())
            if (item := self.products_table.item(row, 0)).checkState() == Qt.Checked
        )

    def _filter_products(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.products_table.rowCount()):
            haystack = " ".join(
                self.products_table.item(row, column).text()
                for column in range(1, 5)
            ).casefold()
            self.products_table.setRowHidden(row, bool(needle and needle not in haystack))

    def _set_checked(self, predicate) -> None:
        self.products_table.blockSignals(True)
        for row in range(self.products_table.rowCount()):
            if predicate(row):
                self.products_table.item(row, 0).setCheckState(Qt.Checked)
        self.products_table.blockSignals(False)
        self._refresh_preview()

    def _select_filtered(self) -> None:
        self._set_checked(lambda row: not self.products_table.isRowHidden(row))

    def _select_published(self) -> None:
        self._set_checked(
            lambda row: bool(self.products_table.item(row, 0).data(Qt.UserRole + 1)))

    def _clear_selection(self) -> None:
        self.products_table.blockSignals(True)
        for row in range(self.products_table.rowCount()):
            self.products_table.item(row, 0).setCheckState(Qt.Unchecked)
        self.products_table.blockSignals(False)
        self._refresh_preview()

    def _price_mode_changed(self) -> None:
        mode = self.price_mode_combo.currentData()
        self.price_value_input.setEnabled(mode in {"percent", "amount", "fixed"})
        self._refresh_preview()

    def _request(self) -> BulkRequest:
        publication_data = self.publication_combo.currentData()
        publication = {"on": True, "off": False}.get(publication_data)
        price_mode = str(self.price_mode_combo.currentData())
        price_value = (
            Decimal(str(self.price_value_input.value()))
            if price_mode in {"percent", "amount", "fixed"}
            else None
        )
        return BulkRequest(
            target_keys=self.selected_keys(),
            publication=publication,
            price_mode=price_mode,
            price_value=price_value,
        )

    def _refresh_preview(self, *_args) -> None:
        self.preview_table.setRowCount(0)
        try:
            preview = build_bulk_preview(self.rows, self._request())
        except ValueError as exc:
            self.preview = None
            self.preview_label.setText(str(exc))
            self.apply_btn.setEnabled(False)
            self.apply_btn.setDefault(False)
            return
        self.preview = preview
        self._fill_preview_table(preview)
        skipped = (
            len(preview.skipped_without_price)
            + len(preview.skipped_below_cost)
            + len(preview.skipped_forced_reset)
        )
        self.preview_label.setText(
            f"Выбрано серий: {len(self.selected_keys())} · публикация: "
            f"{len(preview.series_changes)} · цен: {len(preview.price_changes)} · пропущено: {skipped}"
        )
        enabled = preview.has_changes and not preview.unknown_keys
        self.apply_btn.setEnabled(enabled)
        self.apply_btn.setDefault(enabled)

    def _append_preview_row(self, values: tuple[str, str, str, str]) -> None:
        row = self.preview_table.rowCount()
        self.preview_table.insertRow(row)
        for column, value in enumerate(values):
            self.preview_table.setItem(row, column, QTableWidgetItem(value))

    def _fill_preview_table(self, preview: BulkPreview) -> None:
        for change in preview.series_changes:
            self._append_preview_row((
                change.key,
                "Включено" if change.old_selected else "Выключено",
                "Включено" if change.new_selected else "Выключено",
                "Публикация",
            ))
        for change in preview.price_changes:
            self._append_preview_row((
                change.nc_code,
                "—" if change.old_price is None else f"{change.old_price} ₽",
                "Авто" if change.new_price is None else f"{change.new_price} ₽",
                "Цена",
            ))
        for nc_code in preview.skipped_below_cost:
            self._append_preview_row((nc_code, "—", "—", "Ниже закупочной — пропущено"))
        for nc_code in preview.skipped_without_price:
            self._append_preview_row((nc_code, "—", "—", "Нет цены — пропущено"))
        for nc_code in preview.skipped_forced_reset:
            self._append_preview_row((nc_code, "—", "—", "Нельзя сбросить — пропущено"))
        self.preview_table.resizeColumnsToContents()

    def _apply(self) -> None:
        if self.preview is None or not self.preview.has_changes:
            return
        reply = QMessageBox.question(
            self,
            "Применить массовое изменение?",
            f"Локально изменятся {len(self.preview.series_changes)} серий и "
            f"{len(self.preview.price_changes)} модельных цен. На Avito ничего не отправится.\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            apply_bulk_preview(self.local_cfg, self.preview)
        except Exception as exc:
            QMessageBox.critical(self, "Изменения не сохранены", str(exc))
            return
        self.applied.emit(self.preview)
        self.accept()
