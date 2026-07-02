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


def test_checkbox_toggles_from_raw_int_as_delegate_sends():
    # реальный клик мышью: QStyledItemDelegate передаёт в setData ГОЛЫЙ int (2), а не enum.
    # В PySide6 (6.4+) Qt.CheckState — чистый Python-enum: 2 == Qt.Checked даёт False,
    # из-за чего чекбокс «Публикуется» было невозможно ВКЛЮЧИТЬ мышью.
    model = CatalogTableModel(ROWS)
    idx = model.index(1, model.COL_SELECTED)
    model.setData(idx, 2, Qt.CheckStateRole)          # 2 == Qt.CheckState.Checked.value
    assert model.rows[1].selected is True
    model.setData(idx, 0, Qt.CheckStateRole)          # 0 == Unchecked
    assert model.rows[1].selected is False


def test_price_column_shows_price_range():
    model = CatalogTableModel(ROWS)
    idx = model.index(0, model.COL_PRICE)
    assert model.data(idx, Qt.DisplayRole) == "25990–27990 ₽"


def test_avito_status_column_shows_dash_by_default():
    model = CatalogTableModel(ROWS)
    idx = model.index(0, model.COL_AVITO_STATUS)
    assert model.data(idx, Qt.DisplayRole) == "—"


def test_sort_role_returns_numeric_price_and_stock():
    # сортировка по колонкам «Цена»/«Остаток» должна быть числовой, а не строковой
    # ("9990 ₽" не должно оказываться выше "25990 ₽")
    model = CatalogTableModel(ROWS)
    assert model.data(model.index(0, model.COL_PRICE), Qt.UserRole) == 25990
    assert model.data(model.index(1, model.COL_PRICE), Qt.UserRole) == 19990
    assert model.data(model.index(0, model.COL_STOCK), Qt.UserRole) == 5


def test_sort_role_dashes_sort_below_real_prices():
    rows = [CatalogRow(key="x", source="s", brand="B", series="S", sizes="—",
                       stock_total=0, has_card=False, forced=True, selected=False,
                       representative_nc="НС-9", price_range="—")]
    model = CatalogTableModel(rows)
    assert model.data(model.index(0, model.COL_PRICE), Qt.UserRole) == -1


def test_status_column_colors():
    rows = [
        CatalogRow(key="a", source="s", brand="B", series="S1", sizes="—", stock_total=1,
                   has_card=True, forced=False, selected=True, avito_status="active"),
        CatalogRow(key="b", source="s", brand="B", series="S2", sizes="—", stock_total=1,
                   has_card=False, forced=False, selected=True, avito_status="blocked"),
        CatalogRow(key="c", source="s", brand="B", series="S3", sizes="—", stock_total=1,
                   has_card=False, forced=False, selected=False, avito_status=None),
    ]
    model = CatalogTableModel(rows)
    active = model.data(model.index(0, model.COL_AVITO_STATUS), Qt.ForegroundRole)
    blocked = model.data(model.index(1, model.COL_AVITO_STATUS), Qt.ForegroundRole)
    none = model.data(model.index(2, model.COL_AVITO_STATUS), Qt.ForegroundRole)
    assert active is not None and blocked is not None and none is not None
    assert active.name() != blocked.name()          # «активно» и «заблокировано» различимы
    assert blocked.name() != none.name()


def test_card_checkmark_colored_dash_muted():
    model = CatalogTableModel(ROWS)
    with_card = model.data(model.index(0, model.COL_CARD), Qt.ForegroundRole)
    without_card = model.data(model.index(1, model.COL_CARD), Qt.ForegroundRole)
    assert with_card is not None and without_card is not None
    assert with_card.name() != without_card.name()
