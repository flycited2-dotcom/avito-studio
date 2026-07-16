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


def test_non_forced_row_price_field_editable_and_prefilled_with_computed_price(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    dlg = EditSeriesDialog(_row(price_range="25790–27790 ₽"), root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.price_field.isEnabled() is True   # владелец может поправить цену ЛЮБОЙ серии
    assert dlg.price_field.value() == 25790      # по умолчанию — авторасчёт


def test_non_forced_row_price_unchanged_does_not_create_override(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row(price_range="25990 ₽")
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    dlg.save()   # цену не трогали — override писать не должны
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_price("НС-2") is None


def test_non_forced_row_price_changed_saves_manual_override(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row(price_range="25990 ₽")
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    dlg.price_field.setValue(22990)
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_price("НС-2") == 22990


def test_non_forced_row_prefills_existing_override_instead_of_computed(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_manual_price("НС-2", 22990)
    local_cfg.save()
    # price_range из таблицы после деплоя УЖЕ отражает override (сервер всегда его возвращает) —
    # поле должно показать именно override, а не пытаться «угадать» некий другой авторасчёт.
    row = _row(price_range="22990 ₽")
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.price_field.value() == 22990


def test_non_forced_row_updating_existing_override_to_new_value(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_manual_price("НС-2", 22990)
    local_cfg.save()
    row = _row(price_range="22990 ₽")
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    dlg.price_field.setValue(21990)   # владелец меняет уже существующий override на другое значение
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_price("НС-2") == 21990


def test_non_forced_row_leaving_existing_override_untouched_keeps_it(qtbot, tmp_path):
    """Открыл диалог, ничего не менял, нажал «Сохранить» — override не должен пропасть.
    Явный сброс — только кнопкой «Вернуть авторасчёт» (никакого угадывания «изменил или нет»)."""
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_manual_price("НС-2", 22990)
    local_cfg.save()
    row = _row(price_range="22990 ₽")
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_price("НС-2") == 22990


def test_reset_price_button_removes_existing_override(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_manual_price("НС-2", 22990)
    local_cfg.save()
    row = _row(price_range="22990 ₽")
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    dlg.reset_price_btn.click()
    assert dlg.price_field.isEnabled() is False   # видно, что ручная цена больше не действует
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_price("НС-2") is None


def test_reset_price_button_can_be_toggled_back(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_manual_price("НС-2", 22990)
    local_cfg.save()
    row = _row(price_range="22990 ₽")
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    dlg.reset_price_btn.click()   # передумал
    dlg.reset_price_btn.click()
    assert dlg.price_field.isEnabled() is True
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_price("НС-2") == 22990   # override остался


def test_reset_price_button_hidden_for_forced_rows(qtbot, tmp_path):
    # у товара «под заказ» нет авторасчёта — сбрасывать не к чему
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row(key="rusklimat|force|НС-1", forced=True, representative_nc="НС-1", price_range="18990 ₽")
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.reset_price_btn is None


def test_save_writes_description(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row()
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    dlg.description_edit.setPlainText("Новое описание серии")
    dlg.save()
    assert description_store.get_description(root, row.key) == "Новое описание серии"


def test_save_without_touching_empty_description_does_not_create_manifest_entry(qtbot, tmp_path):
    """Раньше save() ВСЕГДА писал содержимое поля описания — открыл карточку (посмотреть фото,
    сгенерить карточку) и нажал «Сохранить», ничего не тронув → создавался пустой файл-заглушка
    и запись в manifest.json, даже когда автогенерация описания уже работала и трогать её не надо."""
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row()
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    dlg.save()
    import json
    manifest = json.loads((root / "avito-descriptions" / "manifest.json").read_text(encoding="utf-8"))
    assert row.key not in manifest


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


def test_manual_photo_enables_row_in_safe_empty_profile(qtbot, tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "catalog:\n"
        "  force_include: {}\n"
        "  manual_photos: {}\n"
        "  selected_series: [\"__none__\"]\n",
        encoding="utf-8",
    )
    local_cfg = LocalConfig(cfg_path)
    row = _row(forced=False, selected=False)
    dlg = EditSeriesDialog(row, tmp_path, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    photo = tmp_path / "photo-safe.png"
    Image.new("RGB", (4, 4), color="blue").save(photo)
    dlg._new_photo_path = photo
    monkeypatch.setattr("avito_studio.workers.upload_photo_blocking",
                        lambda *a, **k: "https://splithome.ru/static/manual-photos/НС-2.jpg")
    dlg.save()
    reloaded = LocalConfig(cfg_path)
    assert reloaded.is_selected(row.key)
    assert row.selected is True and row.has_card is True


def test_save_photo_upload_failure_raises_for_caller(qtbot, tmp_path):
    # ошибка загрузки должна долететь до main_window (там QMessageBox.critical), а не потеряться
    import pytest
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    photo = tmp_path / "photo.png"
    Image.new("RGB", (4, 4), color="red").save(photo)
    ssh = FakeSsh()

    def boom(remote_path, data):
        raise RuntimeError("No space left on device")
    ssh.put = boom
    dlg = EditSeriesDialog(_row(), root, local_cfg, ssh)
    qtbot.addWidget(dlg)
    dlg._new_photo_path = photo
    with pytest.raises(RuntimeError, match="No space left"):
        dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_manual_photo("НС-2") is None   # URL не записан при провале


def test_utp_field_empty_by_default_and_unchanged_does_not_create_override(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row()
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.utp_edit.toPlainText() == ""
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_card_brief("НС-2") is None


def test_utp_field_changed_saves_card_brief_override(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    row = _row()
    dlg = EditSeriesDialog(row, root, local_cfg, FakeSsh())
    qtbot.addWidget(dlg)
    dlg.utp_edit.setPlainText("Тихий, мощный, Wi-Fi")
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_card_brief("НС-2") == "Тихий, мощный, Wi-Fi"


def test_utp_field_prefilled_with_existing_override(qtbot, tmp_path):
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_card_brief("НС-2", "Тихий, мощный")
    local_cfg.save()
    row = _row()
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    assert dlg.utp_edit.toPlainText() == "Тихий, мощный"


def test_utp_field_cleared_removes_override_instead_of_writing_empty(qtbot, tmp_path):
    # «очистил поле» = «верни автотекст»: снимаем override, а не пишем пустую строку в config
    root = _bridge_root(tmp_path)
    local_cfg = LocalConfig(root / "config" / "config.yaml")
    local_cfg.set_card_brief("НС-2", "Тихий, мощный")
    local_cfg.save()
    row = _row()
    dlg = EditSeriesDialog(row, root, LocalConfig(root / "config" / "config.yaml"), FakeSsh())
    qtbot.addWidget(dlg)
    dlg.utp_edit.setPlainText("")
    dlg.save()
    reloaded = LocalConfig(root / "config" / "config.yaml")
    assert reloaded.get_card_brief("НС-2") is None


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
