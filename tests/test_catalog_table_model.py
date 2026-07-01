from PySide6.QtCore import Qt
from avito_studio.catalog_service import CatalogRow
from avito_studio.catalog_table_model import CatalogTableModel

ROWS = [
    CatalogRow(key="a", source="breeze", brand="Funai", series="Sensei", sizes="7/9 тыс. BTU",
              stock_total=5, has_card=True, forced=False, selected=True,
              representative_nc="НС-1", price_range="25990–27990 ₽"),
    CatalogRow(key="b", source="daichi", brand="Midea", series="Изи", sizes="12 тыс. BTU",
              stock_total=1, has_card=False, forced=False, selected=False,
              representative_nc="НС-3", price_range="19990 ₽"),
]


def test_row_count_and_headers(qtbot):
    model = CatalogTableModel(ROWS)
    assert model.rowCount() == 2
    assert model.headerData(0, Qt.Horizontal) == "Бренд"


def test_display_data_matches_row_fields():
    model = CatalogTableModel(ROWS)
    idx = model.index(0, model.COL_BRAND)
    assert model.data(idx, Qt.DisplayRole) == "Funai"
    idx_card = model.index(1, model.COL_CARD)
    assert model.data(idx_card, Qt.DisplayRole) == "—"


def test_checkbox_column_reflects_and_toggles_selected():
    model = CatalogTableModel(ROWS)
    idx = model.index(1, model.COL_SELECTED)
    assert model.data(idx, Qt.CheckStateRole) == Qt.Unchecked
    model.setData(idx, Qt.Checked, Qt.CheckStateRole)
    assert model.rows[1].selected is True
    assert model.dirty_keys == {"b"}


def test_price_column_shows_price_range():
    model = CatalogTableModel(ROWS)
    idx = model.index(0, model.COL_PRICE)
    assert model.data(idx, Qt.DisplayRole) == "25990–27990 ₽"
