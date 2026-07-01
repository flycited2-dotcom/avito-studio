"""Qt-модель таблицы каталога. Столбец «Публикуется» — чекбокс; переключение сразу правит
объект CatalogRow в памяти и запоминает ключ как «несохранённый» (dirty_keys) — реальная запись
в config.yaml происходит через LocalConfig при нажатии «Сохранить»/«Опубликовать» в главном окне."""
from __future__ import annotations
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from avito_studio.catalog_service import CatalogRow

_HEADERS = ["Бренд", "Серия", "Типоразмеры", "Остаток", "Карточка", "Публикуется"]


class CatalogTableModel(QAbstractTableModel):
    COL_BRAND, COL_SERIES, COL_SIZES, COL_STOCK, COL_CARD, COL_SELECTED = range(6)

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
            return None
        if role != Qt.DisplayRole:
            return None
        return {
            self.COL_BRAND: row.brand,
            self.COL_SERIES: row.series,
            self.COL_SIZES: row.sizes,
            self.COL_STOCK: str(row.stock_total),
            self.COL_CARD: "✓" if row.has_card else "—",
        }.get(col)

    def setData(self, index, value, role=Qt.EditRole):
        if index.column() == self.COL_SELECTED and role == Qt.CheckStateRole:
            row = self.rows[index.row()]
            row.selected = (value == Qt.Checked)
            self.dirty_keys.add(row.key)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False
