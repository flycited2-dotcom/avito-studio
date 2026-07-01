from avito_studio.local_config import LocalConfig

FIXTURE = """\
# комментарий, который должен выжить
cities:
  - { id: "simferopol", name: "Симферополь", avito_location: "Крым" }
pricing:
  default_markup_pct: 5
catalog:
  force_include:
    "НС-1": { price: 18990, series: "ACE-07" }
  manual_photos:
    "НС-2": "https://x/2.jpg"
  selected_series:
    - "breeze|funai|sensei 2.0"
    - "daichi|midea|изи"
"""


def _write(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(FIXTURE, encoding="utf-8")
    return p


def test_is_selected_reflects_yaml(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.is_selected("breeze|funai|sensei 2.0") is True
    assert cfg.is_selected("nope|not|there") is False


def test_set_selected_true_adds_and_saves(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("rusklimat|ballu|tessey dc", True)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.is_selected("rusklimat|ballu|tessey dc") is True
    assert "комментарий, который должен выжить" in path.read_text(encoding="utf-8")


def test_set_selected_false_removes_and_is_idempotent(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("daichi|midea|изи", False)
    cfg.set_selected("daichi|midea|изи", False)   # повторный вызов не должен падать
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.is_selected("daichi|midea|изи") is False
    assert reloaded.is_selected("breeze|funai|sensei 2.0") is True   # остальное не тронуто


def test_selected_series_lists_all(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert set(cfg.selected_series()) == {"breeze|funai|sensei 2.0", "daichi|midea|изи"}


def test_save_preserves_sequence_indentation_style(tmp_path):
    """Без явного yaml.indent(...) ruamel сбрасывает отступ списка при КАЖДОМ save() —
    даёт огромный шумный diff, даже когда правишь одну строку. Список должен остаться
    с отступом в 4 пробела (стиль, уже используемый в реальном config.yaml)."""
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("new|entry|x", True)
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '    - "breeze|funai|sensei 2.0"' in text
    assert '    - "new|entry|x"' in text


def test_get_force_price_reads_existing_entry(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.get_force_price("НС-1") == 18990
    assert cfg.get_force_price("НС-999") is None


def test_set_force_price_updates_existing_entry_and_saves(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_force_price("НС-1", 20990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-1") == 20990
    assert "ACE-07" in path.read_text(encoding="utf-8")   # серия у записи не потерялась


def test_manual_photo_get_set_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_manual_photo("НС-9") is None
    cfg.set_manual_photo("НС-9", "https://splithome.ru/static/manual-photos/НС-9.jpg")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_manual_photo("НС-9") == "https://splithome.ru/static/manual-photos/НС-9.jpg"
    assert reloaded.get_manual_photo("НС-2") == "https://x/2.jpg"   # старая запись не потерялась
