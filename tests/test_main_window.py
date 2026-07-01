from PySide6.QtCore import Qt
from avito_studio.catalog_service import CatalogRow
from avito_studio.main_window import MainWindow

ROWS = [CatalogRow(key="a", source="breeze", brand="Funai", series="Sensei", sizes="7 тыс. BTU",
                   stock_total=2, has_card=True, forced=False, selected=False)]


class FakeSsh:
    def run(self, cmd):
        import json
        return json.dumps({"generated_at": "x", "series": [
            {"key": "a", "source": "breeze", "brand": "Funai", "series": "Sensei",
             "category_id": 2, "stock_total": 2, "has_card": True, "forced": False,
             "members": [{"nc_code": "1", "btu_calc": 7, "stock": 2, "price": 100,
                         "price_ok": True, "forced": False}]}]})


def test_refresh_populates_table_synchronously(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    assert win.model.rowCount() == 1
    assert win.model.rows[0].brand == "Funai"


def test_toggle_checkbox_marks_dirty_and_updates_local_config(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    idx = win.model.index(0, win.model.COL_SELECTED)
    win.model.setData(idx, Qt.Checked, Qt.CheckStateRole)
    win.save_local_selection()
    reloaded_text = cfg_path.read_text(encoding="utf-8")
    assert '"a"' in reloaded_text
