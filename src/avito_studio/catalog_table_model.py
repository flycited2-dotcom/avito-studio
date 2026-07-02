"""Qt-модель таблицы каталога. Столбец «Публикуется» — чекбокс; переключение сразу правит
объект CatalogRow в памяти и запоминает ключ как «несохранённый» (dirty_keys) — реальная запись
в config.yaml происходит через LocalConfig при нажатии «Сохранить»/«Опубликовать» в главном окне.

Qt.UserRole отдаёт СОРТИРОВОЧНЫЕ значения (число для цены/остатка, а не строку "25990 ₽") —
прокси в главном окне сортирует по нему (setSortRole), иначе "9990 ₽" встаёт выше "25990 ₽"."""
from __future__ import annotations
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from avito_studio.catalog_service import CatalogRow, leading_price
from avito_studio.theme import GREEN, RED, MUTED

_HEADERS = ["Бренд", "Серия", "Типоразмеры", "Цена", "Остаток", "Карточка", "Публикуется", "Статус Avito"]

# значения avito_status из /autoload/v4/uploads/last_successful/items
_STATUS_BAD = {"blocked", "rejected", "removed", "archived"}


def _sort_price(price_range: str) -> int:
    p = leading_price(price_range)
    return p if p is not None else -1   # «—» уходит в конец при сортировке по возрастанию


class CatalogTableModel(QAbstractTableModel):
    (COL_BRAND, COL_SERIES, COL_SIZES, COL_PRICE, COL_STOCK, COL_CARD,
     COL_SELECTED, COL_AVITO_STATUS) = range(8)

    def __init__(self, rows: list[CatalogRow], parent=None):
        super().__init__(parent)
        self.rows = rows
        self.dirty_keys: set[str] = set()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _HEADERS[section]
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.column() == self.COL_SELECTED:
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if col == self.COL_SELECTED:
            if role == Qt.CheckStateRole:
                return Qt.Checked if row.selected else Qt.Unchecked
            if role == Qt.UserRole:
                return int(row.selected)
            return None
        if role == Qt.DisplayRole:
            return {
                self.COL_BRAND: row.brand,
                self.COL_SERIES: row.series,
                self.COL_SIZES: row.sizes,
                self.COL_PRICE: row.price_range,
                self.COL_STOCK: str(row.stock_total),
                self.COL_CARD: "✓" if row.has_card else "—",
                self.COL_AVITO_STATUS: row.avito_status or "—",
            }.get(col)
        if role == Qt.UserRole:   # сортировка (см. docstring модуля)
            return {
                self.COL_BRAND: row.brand.lower(),
                self.COL_SERIES: row.series.lower(),
                self.COL_SIZES: row.sizes,
                self.COL_PRICE: _sort_price(row.price_range),
                self.COL_STOCK: row.stock_total,
                self.COL_CARD: int(row.has_card),
                self.COL_AVITO_STATUS: row.avito_status or "",
            }.get(col)
        if role == Qt.ForegroundRole:
            if col == self.COL_CARD:
                return GREEN if row.has_card else MUTED
            if col == self.COL_AVITO_STATUS:
                if not row.avito_status:
                    return MUTED
                return RED if row.avito_status.lower() in _STATUS_BAD else GREEN
            if col == self.COL_STOCK and row.stock_total == 0:
                return MUTED
            if col == self.COL_PRICE and row.price_range == "—":
                return MUTED
            return None
        if role == Qt.TextAlignmentRole:
            if col == self.COL_PRICE:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if col in (self.COL_SIZES, self.COL_STOCK, self.COL_CARD, self.COL_AVITO_STATUS):
                return int(Qt.AlignCenter)
            return None
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.column() == self.COL_SELECTED and role == Qt.CheckStateRole:
            row = self.rows[index.row()]
            # клик мышью приходит от делегата как ГОЛЫЙ int (2), из теста — как enum;
            # Qt.CheckState — чистый Python-enum (2 == Qt.Checked даёт False), нормализуем
            row.selected = (Qt.CheckState(value) == Qt.Checked)
            self.dirty_keys.add(row.key)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False
