from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
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

    def put(self, remote_path, data):
        pass


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


def _win(qtbot, tmp_path, catalog_yaml="catalog:\n  force_include: {}\n  manual_photos: {}\n  selected_series: []\n"):
    # deploy_and_rebuild() тарит bridge_root/config и bridge_root/avito-descriptions — обе папки
    # должны реально существовать, иначе tarfile падает на отсутствующем пути.
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "avito-descriptions").mkdir(exist_ok=True)
    cfg_path = tmp_path / "config" / "config.yaml"
    cfg_path.write_text(catalog_yaml, encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    return win


def test_add_forced_dialog_shows_confirmation_on_success(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    from avito_studio.add_forced_dialog import AddForcedProductDialog
    monkeypatch.setattr(AddForcedProductDialog, "exec", lambda self: 1)
    monkeypatch.setattr(AddForcedProductDialog, "save", lambda self: None)
    shown = {"info": False}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.update(info=True)))
    win._open_add_forced_dialog()
    assert shown["info"] is True


def test_add_forced_dialog_shows_error_on_save_failure(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    from avito_studio.add_forced_dialog import AddForcedProductDialog
    monkeypatch.setattr(AddForcedProductDialog, "exec", lambda self: 1)

    def boom(self):
        raise RuntimeError("network error")
    monkeypatch.setattr(AddForcedProductDialog, "save", boom)
    shown = {"error": False}
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.update(error=True)))
    win._open_add_forced_dialog()   # не должно упасть необработанным исключением
    assert shown["error"] is True


def test_edit_dialog_shows_confirmation_on_success(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    from avito_studio.edit_dialog import EditSeriesDialog
    monkeypatch.setattr(EditSeriesDialog, "exec", lambda self: 1)
    monkeypatch.setattr(EditSeriesDialog, "save", lambda self: None)
    shown = {"info": False}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.update(info=True)))
    win._open_edit_dialog(win.proxy.index(0, 0))
    assert shown["info"] is True


def test_edit_dialog_shows_error_on_save_failure(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    from avito_studio.edit_dialog import EditSeriesDialog
    monkeypatch.setattr(EditSeriesDialog, "exec", lambda self: 1)

    def boom(self):
        raise RuntimeError("upload failed")
    monkeypatch.setattr(EditSeriesDialog, "save", boom)
    shown = {"error": False}
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.update(error=True)))
    win._open_edit_dialog(win.proxy.index(0, 0))   # не должно упасть необработанным исключением
    assert shown["error"] is True


def test_publish_does_not_deploy_when_confirmation_declined(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    win.publish()
    assert win._threads == []


def test_publish_deploys_when_confirmed(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    with qtbot.waitSignal(win.deploy_done, timeout=3000):
        win.publish()
    assert len(win._threads) == 1
