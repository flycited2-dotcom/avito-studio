from PIL import Image
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig
from avito_studio.edit_dialog import EditSeriesDialog
from avito_studio import description_store

FIXTURE_CFG = """\
catalog:
  force_include:
    "НС-1": { price: 18990, series: "ACE-07" }
  manual_photos: {}
  selected_series: []
"""


def _bridge_root(tmp_path):
    root = tmp_path / "avito-bridge"
    (root / "avito-descriptions").mkdir(parents=True)
    (root / "avito-descriptions" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "config.yaml").write_text(FIXTURE_CFG, encoding="utf-8")
    return root


class FakeSsh:
    def __init__(self):
        self.run_calls = []
        self.put_calls = []
        self.run_result = ""

    def run(self, cmd):
        self.run_calls.append(cmd)
        return self.run_result

    def put(self, remote_path, data):
        self.put_calls.append((remote_path, data))


def _row(**overrides):
    base = dict(key="breeze|funai|sensei 2.0", source="breeze", brand="Funai", series="Sensei 2.0",
               sizes="7/9 тыс. BTU", stock_total=5, has_card=True, forced=False, selected=True,
               representative_nc="НС-2", price_range="25990 ₽")
    base.update(overrides)
    return CatalogRow(**base)


def test_forced_row_price_field_editable_and_saved(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row(key="rusklimat|force|НС-1", forced=True, representative_nc="НС-1", price_range="18990 ₽")
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.price_field.isEnabled() is True
    assert dlg.price_field.value() == 18990
    dlg.price_field.setValue(20990)
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_force_price("НС-1") == 20990


def test_non_forced_row_price_field_disabled(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    dlg = EditSeriesDialog(_row(), root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.price_field.isEnabled() is False


def test_non_forced_row_price_field_shows_computed_price(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    dlg = EditSeriesDialog(_row(price_range="25790–27790 ₽"), root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.price_field.value() == 25790   # авторасчёт для инфо, не редактируется


def test_save_writes_description(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row()
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    dlg.description_edit.setPlainText("Новое описание серии")
    dlg.save()
    assert description_store.get_description(root, row.key) == "Новое описание серии"


def test_save_uploads_new_photo_and_stores_url(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    photo = tmp_path / "photo.png"
    Image.new("RGB", (4, 4), color="red").save(photo)
    ssh = FakeSsh()
    row = _row()
    dlg = EditSeriesDialog(row, root, local_cfg, ssh)
    qtbot.addWidget(dlg)
    dlg._new_photo_path = photo
    dlg.save()
    assert len(ssh.put_calls) == 1
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_photo("НС-2") == "https://splithome.ru/static/manual-photos/НС-2.jpg"


def test_generate_card_button_disabled_when_card_exists(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    dlg = EditSeriesDialog(_row(has_card=True), root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.generate_card_btn.isEnabled() is False


def test_generate_card_button_triggers_ssh_call_and_reports_result(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    ssh = FakeSsh()
    ssh.run_result = "cards: series=1 submitted=1 published=0\n"
    row = _row(has_card=False)
    dlg = EditSeriesDialog(row, root, local_cfg, ssh)
    qtbot.addWidget(dlg)
    assert dlg.generate_card_btn.isEnabled() is True
    with qtbot.waitSignal(dlg.card_generation_done, timeout=3000):
        dlg.generate_card_btn.click()
    assert "submitted=1" in dlg.card_status_label.text()
    assert dlg.generate_card_btn.isEnabled() is True   # можно повторить (напр. после смены лимита)
