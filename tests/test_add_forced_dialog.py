from PySide6.QtWidgets import QMessageBox
from avito_studio.local_config import LocalConfig
from avito_studio.add_forced_dialog import AddForcedProductDialog

FIXTURE_CFG = """\
catalog:
  force_include: {}
  manual_photos: {}
  selected_series: []
"""


def test_save_writes_new_force_include_entry(qtbot, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_CFG, encoding="utf-8")
    local_cfg = LocalConfig(path)
    dlg = AddForcedProductDialog(local_cfg)
    qtbot.addWidget(dlg)
    dlg.nc_field.setText("НС-555")
    dlg.price_field.setValue(24990)
    dlg.series_field.setText("Моя серия")
    dlg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-555") == 24990


def test_save_disabled_without_nc_code(qtbot, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_CFG, encoding="utf-8")
    dlg = AddForcedProductDialog(LocalConfig(path))
    qtbot.addWidget(dlg)
    assert dlg.save_btn.isEnabled() is False   # пустой артикул — нельзя сохранить
    dlg.nc_field.setText("НС-1")
    assert dlg.save_btn.isEnabled() is True


def test_zero_price_asks_confirmation_and_does_not_accept_when_declined(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_CFG, encoding="utf-8")
    dlg = AddForcedProductDialog(LocalConfig(path))
    qtbot.addWidget(dlg)
    dlg.nc_field.setText("НС-777")   # цена по умолчанию 0
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    accepted = {"called": False}
    dlg.accept = lambda: accepted.update(called=True)
    dlg.save_btn.click()
    assert accepted["called"] is False   # передумал — диалог не закрывается


def test_zero_price_confirmed_proceeds_to_accept(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_CFG, encoding="utf-8")
    dlg = AddForcedProductDialog(LocalConfig(path))
    qtbot.addWidget(dlg)
    dlg.nc_field.setText("НС-777")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    accepted = {"called": False}
    dlg.accept = lambda: accepted.update(called=True)
    dlg.save_btn.click()
    assert accepted["called"] is True


def test_nonzero_price_accepts_without_asking(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_CFG, encoding="utf-8")
    dlg = AddForcedProductDialog(LocalConfig(path))
    qtbot.addWidget(dlg)
    dlg.nc_field.setText("НС-777")
    dlg.price_field.setValue(19990)
    asked = {"called": False}
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.update(called=True) or QMessageBox.Yes))
    accepted = {"called": False}
    dlg.accept = lambda: accepted.update(called=True)
    dlg.save_btn.click()
    assert asked["called"] is False
    assert accepted["called"] is True
